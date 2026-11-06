# SQL 调用契约

按 `sql/01_schema.sql`、`02_views_triggers.sql`、`03_procedures.sql` 顺序部署到已经创建的新项目数据库。脚本不创建、删除或切换数据库，不清理既有数据。时间统一为 `DATEADD(hour,8,SYSUTCDATETIME())`。

## 写过程

全部参数按下列顺序调用，允许按命名参数执行。`expected_version` 为 `0x` 开头的 16 位十六进制 rowversion，更新必填，新建为 NULL。版本输出先将 rowversion 显式转为 `binary(8)`，再转为十六进制 varchar，避免 timestamp 类型转换差异。成功只返回一个结果集；包含对象 ID、编号（如适用）、status（如适用）、row_version 和 version_hex。幂等重复确认/取消在完成权限及归属检查后返回当前记录，`idempotent` 为 1，不追加历史或审计。

```sql
dbo.usp_SaveBookingDraft
 @actor_id bigint, @booking_id bigint = NULL,
 @customer_id bigint, @voyage_id bigint,
 @cargo_description nvarchar(200), @remark nvarchar(500) = NULL,
 @items_json nvarchar(max), @expected_version varchar(18) = NULL
-- items_json: [{"container_type_id":1,"quantity":2,"total_gross_kg":12000.500}]
-- 草稿允许 []；提交时必须有明细。创建后航次不可改变。

dbo.usp_BookingAction
 @actor_id bigint, @booking_id bigint, @action varchar(20),
 @reason nvarchar(500) = NULL, @expected_version varchar(18) = NULL
-- action: submit / withdraw / reopen / confirm / reject / cancel
-- reject、cancel 必须有原因；不可审核自己创建的订单，ADMIN也不例外。

dbo.usp_SaveVoyage
 @actor_id bigint, @voyage_id bigint = NULL, @voyage_no varchar(30),
 @vessel_id int, @origin_port_id int, @destination_port_id int,
 @departure_at datetime2(0), @arrival_at datetime2(0),
 @booking_cutoff_at datetime2(0), @saleable_teu int,
 @saleable_gross_kg decimal(14,3), @expected_version varchar(18) = NULL
-- 仅草稿可编辑，发布后经营配额、船舶、港口、时刻全部冻结。

dbo.usp_TransitionVoyage
 @actor_id bigint, @voyage_id bigint, @target_status varchar(12),
 @expected_version varchar(18) = NULL
-- DRAFT → OPEN → CLOSED → DEPARTED → COMPLETED。离港前须清空待审单。

dbo.usp_MasterData
 @actor_id bigint, @entity varchar(20), @action varchar(10),
 @id bigint = NULL, @data_json nvarchar(max) = NULL,
 @expected_version varchar(18) = NULL
-- entity: Customer / Port / Vessel；action: save / delete。
-- Customer JSON: customer_code,customer_name,contact_name,contact_phone,email,is_active
-- Port JSON: port_code,port_name,country_region,is_active
-- Vessel JSON: vessel_code,vessel_name,nominal_teu,is_active
-- 新建 is_active 缺省为 true；更新传全对象；删除只传id及version。
-- 返回 id, entity, row_version, version_hex（删除时版本为空）。

dbo.usp_SaveUser
 @actor_id bigint, @user_id bigint = NULL,
 @username nvarchar(50), @display_name nvarchar(50),
 @password_hash varchar(512) = NULL, @is_active bit,
 @roles_json nvarchar(max), @expected_version varchar(18) = NULL
-- roles_json: ["ADMIN","SALES"]；新建必须传hash；更新NULL保留旧hash。
-- 角色只允许ADMIN/SALES/REVIEWER/ANALYST；至少一个；保护最后有效管理员。
```

所有写过程使用事务、XACT_ABORT、TRY/CATCH 回滚。业务错误使用 50000 以上 THROW 中文消息。完整性错误转为可理解的中文消息。`actor_id` 必须来自服务端登录会话，不接受表单指定操作人。

权限：ADMIN 维护客户、港口、船舶、航次、账户和审计，不隐含订单操作权限；SALES 创建、编辑、提交、撤回、重开和取消本人订单，包括航次离港前取消本人已确认单，不维护客户资料；REVIEWER 查看订单并确认或驳回他人提交的订单，不维护航次，不编辑或取消订单；ANALYST 只读统计报表。多角色权限取并集，但确认和驳回始终禁止自审。所有订单写入在航次离港后冻结。

所有订舱写入统一先定位不可变的真实航次，再锁航次行，随后锁订舱行。确认只汇总 CONFIRMED 的 TEU 与明细整行总毛重；总毛重不再乘箱数。仅提交要求客户有效；客户后续停用不会阻止既有待审单确认或离港前取消。主数据停用不会删除历史。降低船舶标称 TEU 前检查其所有未完成航次配额。

账户及角色变更先锁 ADMIN 角色行，再检查是否至少保留一个启用管理员。账户审计快照不包含密码散列。`usp_AssertRole` 是内部辅助过程，不单独授权运行账号。

## 登录查询

`dbo.usp_AuthenticateLookup @username nvarchar(50)` 返回 `user_id, username, display_name, password_hash, is_active, row_version, version_hex`。密码校验由 Python 完成，散列不进入页面或日志。普通 `v_Users` 没有 password_hash。

## 视图字段

- `v_Customers`、`v_Ports`、`v_Vessels`：对应表全部字段，另有 `version_hex`。
- `v_ContainerTypes`、`v_Roles`：对应表全部字段。
- `v_Users`：AppUser 除 password_hash 的字段，另有 `version_hex`。
- `v_UserRoles`：user_id, role_id, role_code, role_name。
- `v_Bookings`：Booking全部字段，以及 customer_name, voyage_no, origin_name, destination_name, departure_at, voyage_status, creator_name, total_boxes, total_teu, total_gross_kg, version_hex。
- `v_BookingItems`：BookingItem全部字段，以及 type_code, type_name, teu_factor。
- `v_BookingHistory`：BookingStatusHistory全部字段，以及 display_name。
- `v_Audit`：AuditLog全部字段，以及 display_name；无密码散列。
- `v_VoyageCapacity`：Voyage全部字段，以及 origin_name, destination_name, vessel_name, nominal_teu, used_teu, used_gross_kg, remaining_teu, remaining_gross_kg, utilization_pct, version_hex。
- 四个主视图为 `v_Bookings`、`v_VoyageCapacity`、`v_CustomerStatistics`、`v_VoyageManifest`。
- `v_CustomerStatistics`：customer_id, customer_code, customer_name, total_bookings, confirmed_bookings, confirmed_boxes, confirmed_teu, confirmed_gross_kg（含零订单客户）。
- `v_VoyageManifest`：voyage_id, voyage_no, booking_id, booking_no, customer_id, customer_name, container_type_id, type_code, quantity, teu, total_gross_kg；只包含CONFIRMED明细。

数据库运行账号授权由部署程序执行：仅 GRANT SELECT 上述视图，EXECUTE 六个公开写过程及 `usp_AuthenticateLookup`，合计七个公开过程。不要对 schema 整体 GRANT EXECUTE，也不要赋予基表 DML。内部辅助过程不授予运行账号。SQL 运行账号由可信 Python 服务持有，网页用户之间的读权限在服务端检查。
