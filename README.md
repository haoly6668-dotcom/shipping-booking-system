# 海运集装箱订舱与航次舱位管理系统

Python Flask + SQL Server 的课程设计程序，面向直达航次整箱订舱。包含客户、港口、船舶、航次、订舱主明细、审核、取消、角色权限、业务历史、操作审计、统计报表与 CSV 导出。

## 在这台电脑上启动

初始化完成后双击 `start.cmd`，保持窗口运行，然后打开 `http://127.0.0.1:5000`。关闭该窗口或按 Ctrl+C 停止服务。默认只监听本机，不依赖外网 CDN。

本次交付已在这台电脑启动后台演示服务，可直接打开上述地址，无需重复启动。双击 `stop.cmd` 可停止本次托管的后台进程；电脑重启后，双击 `start.cmd` 再启动即可。`stop.cmd` 会核对进程归属，不会停止同端口的其他程序。

| 登录名 | 角色 | 演示密码 |
|---|---|---|
| admin | 管理员，维护资料、航次、账户和审计 | Harbor@2026 |
| sales | 业务员，操作本人订舱 | Harbor@2026 |
| sales2 | 第二位业务员，用于归属和并发演示 | Harbor@2026 |
| reviewer | 审核员，确认或驳回他人提交的订单 | Harbor@2026 |
| analyst | 分析员，查询和导出经营报表 | Harbor@2026 |

这些是教学演示账号。密码以带盐哈希存入数据库；数据库运行账号使用另行随机生成的密码保存在本地 `.env`，与上面的网页登录密码无关。管理员不自动拥有业务员或审核员权限，可在用户管理中明确授予额外角色，但任何角色组合都不能审核自己创建的订单。

## 在另一台 Windows 电脑安装

前提：Python 3.12 或以上（本机使用 3.14）、SQL Server 2022 或以上（本机使用 SQL Server 2025 Express）、Microsoft ODBC Driver 18。SQL Server 需允许 SQL 登录，初始化时当前 Windows 账号需要创建专用数据库和登录的权限。程序不会自动修改服务器认证模式。其它版本未在本机实测。

在项目文件夹打开 PowerShell，运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Server localhost
```

命名实例可改为 `-Server '.\SQLEXPRESS'`。脚本在项目内创建虚拟环境，安装固定版本依赖，新建 `HarborBooking` 数据库、数据库对象和教学数据，并生成 `.env`。若同名数据库已存在，初始化会停止以保护原数据；可以使用新的专用库名，例如 `-Database HarborBooking_Class2`，再将生成的对应配置文件复制为 `.env`。不要把别人的数据库名传入脚本。

安装依赖需要网络，已安装后网页运行无需网络。`setup.ps1` 中的执行策略参数仅作用于这一次进程，不永久修改系统设置。启动入口是 `start.cmd`，或者在已安装依赖的环境中运行 `python run.py`。

## 演示顺序

1. `admin` 登录，查看基础资料和航次。创建 DRAFT 航次并发布为 OPEN，或使用现成数据。
2. `sales` 登录，在航次页选择开放航次，建立订舱草稿；填写箱型、箱数和每行全部箱子的总毛重，保存并提交。
3. `reviewer` 登录，打开待审订舱详情，核对所需 TEU、重量和航次余量，然后确认或带理由驳回。
4. 回到 `sales`，查看时间线；离港前取消自己的已确认订舱，查看容量恢复。
5. `analyst` 登录，按计划离港日期查看月度、客户和港口对报表，并导出同一筛选下的 CSV。
6. `admin` 查看操作审计。演示删除一个未被引用的新客户，再尝试删除已被订舱引用的客户，说明外键保护。

初始化提供 8 个港口、6 艘船、20 个客户、24 个航次、3 个箱型和 83 张混合状态订舱。所有数据为模拟数据。`DEMO-001` 固定为 10 TEU / 40,000 kg，基线占用 4 TEU / 12,000 kg，两个待审订单各需 4 TEU，因此剩余 6 TEU 最多允许其中一张确认。其他航次用于常规业务演示。

日期按初始化时的北京时间生成，截止时间位于未来。数据库长期保留后截止时间自然会到期；需要新一轮课堂演示时通过管理界面创建新航次，不直接篡改已发布航次计划。

## 数据库与程序结构

- `app/routes.py`：登录、CSRF、权限、页面和接口。
- `app/services.py`：输入校验、业务服务、统计口径和 CSV。
- `app/db.py`：ODBC 查询、命名参数过程调用、连接生命周期和错误映射。
- `app/templates/`、`app/static/`：本地网页模板、样式和交互。
- `sql/01_schema.sql`：12 张表、主外键、CHECK、唯一约束、索引、单号序列及固定字典。
- `sql/02_views_triggers.sql`：业务视图和集合式触发器。
- `sql/03_procedures.sql`：所有业务写入的存储过程。
- `sql/04_query_examples.sql`：可在 SSMS 运行的 JOIN、GROUP BY/HAVING、NOT EXISTS、CTE、LAG、DENSE_RANK 及容量核对示例。
- `scripts/setup_database.py`：新库部署、合法流程种子数据、运行账号最小授权。
- `tests/`：真实 SQL Server 集成测试及 HTTP 层测试。

订舱状态为 DRAFT → SUBMITTED → CONFIRMED 或 REJECTED；允许撤回、驳回后修订及符合条件的取消。只有 CONFIRMED 占用配额，实时聚合明细，不保存第二份余额。每条明细的 `total_gross_kg` 是这一行的总毛重，不能再乘箱数。

确认、取消、保存和航次状态变更统一先锁航次再锁订单，在事务内重新验证状态、版本及双配额；状态历史和成功操作审计与业务同成同败。前端余量仅作预览。发布后冻结航次计划与配额，关闭或达到截止时间后不能提交或确认，离港后不能取消已确认订单。

应用通过服务器端会话确定操作者，不信任表单内的用户 ID。运行 SQL 登录只获授权视图的 SELECT 和公开业务过程的 EXECUTE；无基表 DML、DDL 或 db_owner。该模型信任本机 Python 服务；课程演示不是开放互联网服务。

## 测试与备份

安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/setup_database.py --database HarborBooking_Test
.\.venv\Scripts\python.exe -m pytest -q
```

测试仅使用名称以 `_Test` 结尾的独立数据库。具体测试环境变量和实测结果见 `docs/测试结果.md`。不得将测试连接串设置为已有业务库。故障注入只在测试库执行，不在正常程序保留隐藏失败开关。

提交源码时包含全部 SQL、配置示例和依赖清单，不提交 `.env` 或本机虚拟环境。数据库备份与恢复说明见 `docs/数据库备份.md`。原设计材料仍放在工作区的“项目设计方案”文件夹，个人报告应结合实际运行截图和各自工作独立撰写。
