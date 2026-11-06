SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO
-- Internal helper: deliberately not granted to the application login.
CREATE OR ALTER PROCEDURE dbo.usp_AssertRole @actor_id bigint,@role_code varchar(30) AS
BEGIN
 SET NOCOUNT ON;
 IF NOT EXISTS(SELECT 1 FROM dbo.AppUser u JOIN dbo.UserRole ur ON ur.user_id=u.user_id
 JOIN dbo.[Role] r ON r.role_id=ur.role_id WHERE u.user_id=@actor_id AND u.is_active=1 AND r.role_code=@role_code)
  THROW 50001,N'当前账号没有此操作权限，或已被停用。',1;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_MasterData
 @actor_id bigint,@entity varchar(20),@action varchar(10),@id bigint=NULL,@data_json nvarchar(max)=NULL,@expected_version varchar(18)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRANSACTION;
  EXEC dbo.usp_AssertRole @actor_id,'ADMIN';
  IF @entity IS NULL OR @entity NOT IN ('Customer','Port','Vessel') OR @action IS NULL OR @action NOT IN ('save','delete')
   THROW 50041,N'未知基础资料操作。',1;
  DECLARE @rv binary(8),@before nvarchar(max),@after nvarchar(max),@lockvoyage bigint;
  IF @id IS NOT NULL
  BEGIN
   -- Follow Voyage -> Vessel order when a capacity-bearing vessel is modified.
   IF @entity='Vessel' SELECT @lockvoyage=voyage_id FROM dbo.Voyage WITH(UPDLOCK,HOLDLOCK) WHERE vessel_id=@id AND status<>'COMPLETED' ORDER BY voyage_id;
   IF @entity='Customer'
   BEGIN
    SELECT @rv=row_version FROM dbo.Customer WITH(UPDLOCK,HOLDLOCK) WHERE customer_id=@id;
    SET @before=(SELECT * FROM dbo.Customer WHERE customer_id=@id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   END;
   IF @entity='Port'
   BEGIN
    SELECT @rv=row_version FROM dbo.Port WITH(UPDLOCK,HOLDLOCK) WHERE port_id=@id;
    SET @before=(SELECT * FROM dbo.Port WHERE port_id=@id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   END;
   IF @entity='Vessel'
   BEGIN
    SELECT @rv=row_version FROM dbo.Vessel WITH(UPDLOCK,HOLDLOCK) WHERE vessel_id=@id;
    SET @before=(SELECT * FROM dbo.Vessel WHERE vessel_id=@id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   END;
   IF @rv IS NULL THROW 50042,N'资料不存在。',1;
   IF @expected_version IS NULL OR LEN(@expected_version)<>18 OR TRY_CONVERT(binary(8),@expected_version,1) IS NULL OR TRY_CONVERT(binary(8),@expected_version,1)<>@rv
    THROW 50018,N'数据已被其他操作修改，请刷新后重试。',1;
  END;
  IF @action='delete'
  BEGIN
   IF @id IS NULL THROW 50042,N'请指定待删除的资料。',1;
   IF @entity='Customer'
   BEGIN
    IF EXISTS(SELECT 1 FROM dbo.Booking WHERE customer_id=@id) THROW 50043,N'该客户已被订舱引用，请停用而不要删除。',1;
    DELETE dbo.Customer WHERE customer_id=@id;
   END;
   IF @entity='Port'
   BEGIN
    IF EXISTS(SELECT 1 FROM dbo.Voyage WHERE origin_port_id=@id OR destination_port_id=@id) THROW 50043,N'该港口已被航次引用，请停用而不要删除。',1;
    DELETE dbo.Port WHERE port_id=@id;
   END;
   IF @entity='Vessel'
   BEGIN
    IF EXISTS(SELECT 1 FROM dbo.Voyage WHERE vessel_id=@id) THROW 50043,N'该船舶已被航次引用，请停用而不要删除。',1;
    DELETE dbo.Vessel WHERE vessel_id=@id;
   END;
   SET @rv=NULL;
  END
  ELSE
  BEGIN
   IF ISNULL(ISJSON(@data_json),0)<>1 OR LEFT(LTRIM(@data_json),1)<>'{' THROW 50044,N'基础资料必须是 JSON 对象。',1;
   DECLARE @code nvarchar(4000),@name nvarchar(4000),@contact nvarchar(4000),@phone nvarchar(4000),@email nvarchar(4000),
    @country nvarchar(4000),@nominal int,@active bit,@active_text nvarchar(10);
   SET @active_text=JSON_VALUE(@data_json,'$.is_active');
   IF @active_text IS NOT NULL AND @active_text NOT IN ('true','false','1','0') THROW 50044,N'启用状态必须为 true 或 false。',1;
   SET @active=CASE WHEN @active_text IN ('false','0') THEN 0 ELSE 1 END;
   IF @entity='Customer'
   BEGIN
    SELECT @code=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.customer_code'))),@name=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.customer_name'))),
     @contact=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.contact_name'))),@phone=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.contact_phone'))),@email=NULLIF(LTRIM(RTRIM(JSON_VALUE(@data_json,'$.email'))),'');
    IF NULLIF(@code,'') IS NULL OR LEN(@code)>20 OR NULLIF(@name,'') IS NULL OR LEN(@name)>100 OR NULLIF(@contact,'') IS NULL OR LEN(@contact)>50
     OR NULLIF(@phone,'') IS NULL OR LEN(@phone)>30 OR LEN(@email)>254 THROW 50045,N'请完整填写客户资料，并检查字段长度。',1;
    IF @id IS NULL
    BEGIN
     INSERT dbo.Customer(customer_code,customer_name,contact_name,contact_phone,email,is_active) VALUES(@code,@name,@contact,@phone,@email,@active);
     SET @id=SCOPE_IDENTITY();
    END
    ELSE UPDATE dbo.Customer SET customer_code=@code,customer_name=@name,contact_name=@contact,contact_phone=@phone,email=@email,is_active=@active WHERE customer_id=@id;
    SELECT @rv=row_version FROM dbo.Customer WHERE customer_id=@id;
    SET @after=(SELECT * FROM dbo.Customer WHERE customer_id=@id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   END;
   IF @entity='Port'
   BEGIN
    SELECT @code=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.port_code'))),@name=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.port_name'))),@country=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.country_region')));
    IF NULLIF(@code,'') IS NULL OR LEN(@code)>10 OR NULLIF(@name,'') IS NULL OR LEN(@name)>100 OR NULLIF(@country,'') IS NULL OR LEN(@country)>60
     THROW 50046,N'请完整填写港口资料，并检查字段长度。',1;
    IF @id IS NULL
    BEGIN
     INSERT dbo.Port(port_code,port_name,country_region,is_active) VALUES(@code,@name,@country,@active);
     SET @id=SCOPE_IDENTITY();
    END
    ELSE UPDATE dbo.Port SET port_code=@code,port_name=@name,country_region=@country,is_active=@active WHERE port_id=@id;
    SELECT @rv=row_version FROM dbo.Port WHERE port_id=@id;
    SET @after=(SELECT * FROM dbo.Port WHERE port_id=@id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   END;
   IF @entity='Vessel'
   BEGIN
    SELECT @code=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.vessel_code'))),@name=LTRIM(RTRIM(JSON_VALUE(@data_json,'$.vessel_name'))),@nominal=TRY_CONVERT(int,JSON_VALUE(@data_json,'$.nominal_teu'));
    IF NULLIF(@code,'') IS NULL OR LEN(@code)>20 OR NULLIF(@name,'') IS NULL OR LEN(@name)>100 OR @nominal IS NULL OR @nominal<=0
     OR TRY_CONVERT(decimal(38,9),JSON_VALUE(@data_json,'$.nominal_teu'))<>@nominal THROW 50047,N'请完整填写船舶资料；标称 TEU 必须为正整数。',1;
    IF @id IS NOT NULL AND EXISTS(SELECT 1 FROM dbo.Voyage WHERE vessel_id=@id AND status<>'COMPLETED' AND saleable_teu>@nominal)
     THROW 50048,N'标称容量不能低于该船未完成航次的可售 TEU 配额。',1;
    IF @id IS NULL
    BEGIN
     INSERT dbo.Vessel(vessel_code,vessel_name,nominal_teu,is_active) VALUES(@code,@name,@nominal,@active);
     SET @id=SCOPE_IDENTITY();
    END
    ELSE UPDATE dbo.Vessel SET vessel_code=@code,vessel_name=@name,nominal_teu=@nominal,is_active=@active WHERE vessel_id=@id;
    SELECT @rv=row_version FROM dbo.Vessel WHERE vessel_id=@id;
    SET @after=(SELECT * FROM dbo.Vessel WHERE vessel_id=@id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   END;
  END;
  INSERT dbo.AuditLog(actor_user_id,action_code,entity_name,entity_key,before_json,after_json)
   VALUES(@actor_id,CASE WHEN @action='delete' THEN 'DELETE' WHEN @before IS NULL THEN 'CREATE' ELSE 'UPDATE' END,@entity,CONVERT(nvarchar(128),@id),@before,@after);
  COMMIT;
  SELECT @id id,@entity entity,@rv row_version,CONVERT(varchar(18),@rv,1) version_hex;
 END TRY
 BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK;
  IF ERROR_NUMBER() IN (2601,2627) THROW 50049,N'编号已经存在，请使用其他编号。',1;
  IF ERROR_NUMBER()=547 THROW 50043,N'资料已被其他记录引用，不能删除；可改为停用。',1;
  THROW;
 END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_SaveUser
 @actor_id bigint,@user_id bigint=NULL,@username nvarchar(50),@display_name nvarchar(50),@password_hash varchar(512)=NULL,
 @is_active bit,@roles_json nvarchar(max),@expected_version varchar(18)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRANSACTION;
  DECLARE @admin_role int,@rv binary(8),@before nvarchar(max),@after nvarchar(max);
  -- Serialize every membership/activation change at one row to protect the last administrator.
  SELECT @admin_role=role_id FROM dbo.[Role] WITH(UPDLOCK,HOLDLOCK) WHERE role_code='ADMIN';
  EXEC dbo.usp_AssertRole @actor_id,'ADMIN';
  IF NULLIF(LTRIM(RTRIM(@username)),N'') IS NULL OR NULLIF(LTRIM(RTRIM(@display_name)),N'') IS NULL OR @is_active IS NULL
   THROW 50050,N'用户名、姓名和启用状态不能为空。',1;
  IF ISNULL(ISJSON(@roles_json),0)<>1 OR LEFT(LTRIM(@roles_json),1)<>'[' THROW 50051,N'角色必须为 JSON 数组。',1;
  IF NOT EXISTS(SELECT 1 FROM OPENJSON(@roles_json)) OR EXISTS(SELECT 1 FROM OPENJSON(@roles_json) j WHERE [type]<>1 OR NOT EXISTS(SELECT 1 FROM dbo.[Role] r WHERE r.role_code=j.value))
   OR EXISTS(SELECT value FROM OPENJSON(@roles_json) GROUP BY value HAVING COUNT(*)>1) THROW 50051,N'至少选择一个有效角色，角色不能重复。',1;
  IF @user_id IS NOT NULL
  BEGIN
   SELECT @rv=row_version FROM dbo.AppUser WITH(UPDLOCK,HOLDLOCK) WHERE user_id=@user_id;
   IF @rv IS NULL THROW 50052,N'用户不存在。',1;
   IF @expected_version IS NULL OR LEN(@expected_version)<>18 OR TRY_CONVERT(binary(8),@expected_version,1) IS NULL OR TRY_CONVERT(binary(8),@expected_version,1)<>@rv
    THROW 50018,N'数据已被其他操作修改，请刷新后重试。',1;
   SET @before=(SELECT u.user_id,u.username,u.display_name,u.is_active,
    JSON_QUERY((SELECT r.role_code FROM dbo.UserRole ur JOIN dbo.[Role] r ON r.role_id=ur.role_id WHERE ur.user_id=u.user_id FOR JSON PATH)) roles
    FROM dbo.AppUser u WHERE u.user_id=@user_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  END;
  IF (@user_id IS NULL AND NULLIF(@password_hash,'') IS NULL) OR @password_hash=''
   THROW 50053,N'新用户必须设置密码散列，更新密码不能为空。',1;
  IF @user_id IS NULL
  BEGIN
   INSERT dbo.AppUser(username,display_name,password_hash,is_active) VALUES(LTRIM(RTRIM(@username)),LTRIM(RTRIM(@display_name)),@password_hash,@is_active);
   SET @user_id=SCOPE_IDENTITY();
  END
  ELSE UPDATE dbo.AppUser SET username=LTRIM(RTRIM(@username)),display_name=LTRIM(RTRIM(@display_name)),password_hash=COALESCE(@password_hash,password_hash),is_active=@is_active WHERE user_id=@user_id;
  DELETE dbo.UserRole WHERE user_id=@user_id;
  INSERT dbo.UserRole(user_id,role_id,assigned_by) SELECT @user_id,r.role_id,@actor_id FROM OPENJSON(@roles_json) j JOIN dbo.[Role] r ON r.role_code=j.value;
  IF NOT EXISTS(SELECT 1 FROM dbo.AppUser u JOIN dbo.UserRole ur ON ur.user_id=u.user_id WHERE ur.role_id=@admin_role AND u.is_active=1)
   THROW 50054,N'必须保留至少一个启用的系统管理员。',1;
  SET @after=(SELECT u.user_id,u.username,u.display_name,u.is_active,
   JSON_QUERY((SELECT r.role_code FROM dbo.UserRole ur JOIN dbo.[Role] r ON r.role_id=ur.role_id WHERE ur.user_id=u.user_id FOR JSON PATH)) roles
   FROM dbo.AppUser u WHERE u.user_id=@user_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  INSERT dbo.AuditLog(actor_user_id,action_code,entity_name,entity_key,before_json,after_json)
   VALUES(@actor_id,CASE WHEN @before IS NULL THEN 'CREATE' ELSE 'UPDATE' END,'AppUser',CONVERT(nvarchar(128),@user_id),@before,@after);
  COMMIT;
  SELECT user_id,username,display_name,is_active,row_version,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex FROM dbo.AppUser WHERE user_id=@user_id;
 END TRY
 BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK;
  IF ERROR_NUMBER() IN (2601,2627) THROW 50055,N'用户名已经存在，请更换用户名。',1;
  THROW;
 END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_AuthenticateLookup @username nvarchar(50) AS
BEGIN
 SET NOCOUNT ON;
 SELECT user_id,username,display_name,password_hash,is_active,row_version,
 CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex FROM dbo.AppUser WHERE username=@username;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_SaveBookingDraft
 @actor_id bigint,@booking_id bigint=NULL,@customer_id bigint,@voyage_id bigint,
 @cargo_description nvarchar(200),@remark nvarchar(500)=NULL,@items_json nvarchar(max),@expected_version varchar(18)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRANSACTION;
  EXEC dbo.usp_AssertRole @actor_id,'SALES';
  IF NULLIF(LTRIM(RTRIM(@cargo_description)),N'') IS NULL THROW 50010,N'请填写货物描述。',1;
  IF ISNULL(ISJSON(@items_json),0)<>1 OR LEFT(LTRIM(@items_json),1)<>'[' THROW 50011,N'箱型明细必须是 JSON 数组。',1;
  IF (SELECT COUNT(*) FROM OPENJSON(@items_json))>3 OR EXISTS(SELECT 1 FROM OPENJSON(@items_json) WHERE [type]<>5)
   THROW 50011,N'箱型明细格式不正确，最多三个不同箱型。',1;
  DECLARE @items TABLE(container_type_id int,quantity bigint,total_gross_kg decimal(38,9));
  INSERT @items SELECT TRY_CONVERT(int,JSON_VALUE(value,'$.container_type_id')),
   TRY_CONVERT(bigint,JSON_VALUE(value,'$.quantity')),TRY_CONVERT(decimal(38,9),JSON_VALUE(value,'$.total_gross_kg')) FROM OPENJSON(@items_json);
  IF EXISTS(SELECT 1 FROM @items WHERE container_type_id IS NULL OR quantity IS NULL OR quantity<=0 OR quantity>2147483647
   OR total_gross_kg IS NULL OR total_gross_kg<=0 OR total_gross_kg>=100000000000 OR total_gross_kg<>ROUND(total_gross_kg,3))
   OR EXISTS(SELECT container_type_id FROM @items GROUP BY container_type_id HAVING COUNT(*)>1)
   OR EXISTS(SELECT 1 FROM @items i WHERE NOT EXISTS(SELECT 1 FROM dbo.ContainerType t WHERE t.container_type_id=i.container_type_id))
   THROW 50011,N'箱型不可重复，箱数须为正整数，总毛重须为正数且最多三位小数。',1;
  -- Avoid silent conversion of JSON fractional quantities/type identifiers.
  IF EXISTS(SELECT 1 FROM OPENJSON(@items_json) WHERE
   TRY_CONVERT(decimal(38,9),JSON_VALUE(value,'$.quantity'))<>TRY_CONVERT(bigint,JSON_VALUE(value,'$.quantity')) OR
   TRY_CONVERT(decimal(38,9),JSON_VALUE(value,'$.container_type_id'))<>TRY_CONVERT(int,JSON_VALUE(value,'$.container_type_id')))
   THROW 50011,N'箱型编号及箱数必须是整数。',1;
  DECLARE @vstatus varchar(12),@oldstatus varchar(12),@owner bigint,@oldvoyage bigint,@rv binary(8),@before nvarchar(max),@after nvarchar(max),@lock_voyage_id bigint=@voyage_id;
  IF @booking_id IS NOT NULL
  BEGIN
   -- Discover the immutable parent before taking update locks; never lock a
   -- caller-supplied different voyage before the existing order's real parent.
   SELECT @lock_voyage_id=voyage_id FROM dbo.Booking WHERE booking_id=@booking_id;
   IF @@ROWCOUNT=0 THROW 50015,N'订舱单不存在。',1;
   IF @lock_voyage_id<>@voyage_id THROW 50016,N'订舱创建后不能变更航次，请取消后重新建单。',1;
  END;
  -- Every booking mutation takes the common voyage lock before any booking lock.
  SELECT @vstatus=status FROM dbo.Voyage WITH(UPDLOCK,HOLDLOCK) WHERE voyage_id=@lock_voyage_id;
  IF @vstatus IS NULL THROW 50012,N'所选航次不存在。',1;
  IF @vstatus IN ('DEPARTED','COMPLETED') THROW 50013,N'航次已经离港，订舱不可修改。',1;
  IF NOT EXISTS(SELECT 1 FROM dbo.Customer WHERE customer_id=@customer_id AND is_active=1) THROW 50014,N'请选择有效客户。',1;
  IF @booking_id IS NULL
  BEGIN
   IF @vstatus<>'OPEN' THROW 50013,N'仅可为已开放航次创建订舱。',1;
   DECLARE @seq bigint=NEXT VALUE FOR dbo.BookingNumber;
   DECLARE @no varchar(30)='BK'+CONVERT(char(8),DATEADD(hour,8,SYSUTCDATETIME()),112)+'-'+CONVERT(varchar(20),@seq);
   INSERT dbo.Booking(booking_no,customer_id,voyage_id,cargo_description,remark,created_by,last_changed_by,status_reason)
    VALUES(@no,@customer_id,@voyage_id,LTRIM(RTRIM(@cargo_description)),@remark,@actor_id,@actor_id,N'新建草稿');
   SET @booking_id=SCOPE_IDENTITY();
  END
  ELSE
  BEGIN
   SELECT @oldstatus=status,@owner=created_by,@oldvoyage=voyage_id,@rv=row_version FROM dbo.Booking WITH(UPDLOCK,HOLDLOCK) WHERE booking_id=@booking_id;
   IF @oldstatus IS NULL THROW 50015,N'订舱单不存在。',1;
   IF @owner<>@actor_id THROW 50001,N'只能修改本人创建的订舱。',1;
   IF @oldvoyage<>@voyage_id THROW 50016,N'订舱创建后不能变更航次，请取消后重新建单。',1;
   IF @oldstatus<>'DRAFT' THROW 50017,N'只有草稿可以编辑。',1;
   IF @expected_version IS NULL OR LEN(@expected_version)<>18 OR TRY_CONVERT(binary(8),@expected_version,1) IS NULL OR TRY_CONVERT(binary(8),@expected_version,1)<>@rv
    THROW 50018,N'数据已被其他操作修改，请刷新后重试。',1;
   SET @before=(SELECT b.*,JSON_QUERY((SELECT * FROM dbo.BookingItem WHERE booking_id=@booking_id FOR JSON PATH)) items FROM dbo.Booking b WHERE booking_id=@booking_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
   UPDATE dbo.Booking SET customer_id=@customer_id,cargo_description=LTRIM(RTRIM(@cargo_description)),remark=@remark,last_changed_by=@actor_id,
    updated_at=DATEADD(hour,8,SYSUTCDATETIME()),status_reason=N'编辑草稿' WHERE booking_id=@booking_id;
   DELETE dbo.BookingItem WHERE booking_id=@booking_id;
  END;
  INSERT dbo.BookingItem(booking_id,container_type_id,quantity,total_gross_kg) SELECT @booking_id,container_type_id,quantity,total_gross_kg FROM @items;
  SET @after=(SELECT b.*,JSON_QUERY((SELECT * FROM dbo.BookingItem WHERE booking_id=@booking_id FOR JSON PATH)) items FROM dbo.Booking b WHERE booking_id=@booking_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  INSERT dbo.AuditLog(actor_user_id,action_code,entity_name,entity_key,before_json,after_json)
   VALUES(@actor_id,CASE WHEN @before IS NULL THEN 'CREATE' ELSE 'UPDATE' END,'Booking',CONVERT(nvarchar(128),@booking_id),@before,@after);
  COMMIT;
  SELECT booking_id,booking_no,status,row_version,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex FROM dbo.Booking WHERE booking_id=@booking_id;
 END TRY
 BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK;
  THROW;
 END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_BookingAction
 @actor_id bigint,@booking_id bigint,@action varchar(20),@reason nvarchar(500)=NULL,@expected_version varchar(18)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRANSACTION;
  IF @action IS NULL OR @action NOT IN ('submit','withdraw','reopen','confirm','reject','cancel') THROW 50020,N'未知订舱操作。',1;
  IF @action IN ('confirm','reject') EXEC dbo.usp_AssertRole @actor_id,'REVIEWER';
  ELSE EXEC dbo.usp_AssertRole @actor_id,'SALES';
  DECLARE @voyage_id bigint,@vstatus varchar(12),@cutoff datetime2(0),@status varchar(12),@owner bigint,@rv binary(8),
   @target varchar(12),@before nvarchar(max),@after nvarchar(max),@quota_teu bigint,@quota_kg decimal(38,3);
  -- This read only discovers the immutable voyage identifier; it takes no update lock.
  SELECT @voyage_id=voyage_id FROM dbo.Booking WHERE booking_id=@booking_id;
  IF @voyage_id IS NULL THROW 50015,N'订舱单不存在。',1;
  SELECT @vstatus=status,@cutoff=booking_cutoff_at,@quota_teu=saleable_teu,@quota_kg=saleable_gross_kg
   FROM dbo.Voyage WITH(UPDLOCK,HOLDLOCK) WHERE voyage_id=@voyage_id;
  SELECT @status=status,@owner=created_by,@rv=row_version FROM dbo.Booking WITH(UPDLOCK,HOLDLOCK) WHERE booking_id=@booking_id;
  IF @action IN ('confirm','reject') AND @owner=@actor_id THROW 50021,N'不能审核本人创建的订舱。',1;
  IF @action NOT IN ('confirm','reject') AND @owner<>@actor_id THROW 50001,N'只能操作本人创建的订舱。',1;
  -- Safe retries return the committed record without a second audit/history entry.
  IF (@action='confirm' AND @status='CONFIRMED') OR (@action='cancel' AND @status='CANCELLED')
  BEGIN
   COMMIT;
   SELECT booking_id,booking_no,status,row_version,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex,CAST(1 AS bit) idempotent FROM dbo.Booking WHERE booking_id=@booking_id;
   RETURN;
  END;
  IF @vstatus IN ('DEPARTED','COMPLETED') THROW 50013,N'航次已经离港，订舱不可修改。',1;
  IF @expected_version IS NULL OR LEN(@expected_version)<>18 OR TRY_CONVERT(binary(8),@expected_version,1) IS NULL OR TRY_CONVERT(binary(8),@expected_version,1)<>@rv
   THROW 50018,N'数据已被其他操作修改，请刷新后重试。',1;
  IF @action IN ('reject','cancel') AND NULLIF(LTRIM(RTRIM(@reason)),N'') IS NULL THROW 50022,N'驳回或取消时必须填写原因。',1;
  SET @target=CASE WHEN @action='submit' AND @status='DRAFT' THEN 'SUBMITTED'
   WHEN @action='withdraw' AND @status='SUBMITTED' THEN 'DRAFT'
   WHEN @action='reopen' AND @status='REJECTED' THEN 'DRAFT'
   WHEN @action='confirm' AND @status='SUBMITTED' THEN 'CONFIRMED'
   WHEN @action='reject' AND @status='SUBMITTED' THEN 'REJECTED'
   WHEN @action='cancel' AND @status IN ('DRAFT','SUBMITTED','REJECTED','CONFIRMED') THEN 'CANCELLED' END;
  IF @target IS NULL THROW 50023,N'当前订舱状态不允许执行该操作。',1;
  IF @action IN ('submit','confirm')
  BEGIN
   IF @vstatus<>'OPEN' OR @cutoff<=DATEADD(hour,8,SYSUTCDATETIME()) THROW 50024,N'航次未开放或已超过截单时间。',1;
   IF NOT EXISTS(SELECT 1 FROM dbo.BookingItem WHERE booking_id=@booking_id) THROW 50025,N'空草稿不能提交，请至少填写一条箱型明细。',1;
   IF @action='submit' AND NOT EXISTS(SELECT 1 FROM dbo.Booking b JOIN dbo.Customer c ON c.customer_id=b.customer_id WHERE b.booking_id=@booking_id AND c.is_active=1)
    THROW 50014,N'客户已停用，不能提交。',1;
  END;
  IF @action='confirm'
  BEGIN
   DECLARE @used_teu bigint,@used_kg decimal(38,3),@need_teu bigint,@need_kg decimal(38,3);
   SELECT @used_teu=COALESCE(SUM(CONVERT(bigint,i.quantity)*t.teu_factor),0),@used_kg=COALESCE(SUM(i.total_gross_kg),0)
    FROM dbo.Booking b JOIN dbo.BookingItem i ON i.booking_id=b.booking_id JOIN dbo.ContainerType t ON t.container_type_id=i.container_type_id
    WHERE b.voyage_id=@voyage_id AND b.status='CONFIRMED';
   SELECT @need_teu=SUM(CONVERT(bigint,i.quantity)*t.teu_factor),@need_kg=SUM(i.total_gross_kg)
    FROM dbo.BookingItem i JOIN dbo.ContainerType t ON t.container_type_id=i.container_type_id WHERE booking_id=@booking_id;
   IF @used_teu+@need_teu>@quota_teu THROW 50026,N'剩余 TEU 舱位不足，确认失败。',1;
   IF @used_kg+@need_kg>@quota_kg THROW 50027,N'剩余总毛重配额不足，确认失败。',1;
  END;
  SET @before=(SELECT * FROM dbo.Booking WHERE booking_id=@booking_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  UPDATE dbo.Booking SET status=@target,last_changed_by=@actor_id,status_reason=@reason,updated_at=DATEADD(hour,8,SYSUTCDATETIME()) WHERE booking_id=@booking_id;
  SET @after=(SELECT * FROM dbo.Booking WHERE booking_id=@booking_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  INSERT dbo.AuditLog(actor_user_id,action_code,entity_name,entity_key,before_json,after_json)
   VALUES(@actor_id,UPPER(@action),'Booking',CONVERT(nvarchar(128),@booking_id),@before,@after);
  COMMIT;
  SELECT booking_id,booking_no,status,row_version,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex,CAST(0 AS bit) idempotent FROM dbo.Booking WHERE booking_id=@booking_id;
 END TRY
 BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK;
  THROW;
 END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_SaveVoyage
 @actor_id bigint,@voyage_id bigint=NULL,@voyage_no varchar(30),@vessel_id int,@origin_port_id int,@destination_port_id int,
 @departure_at datetime2(0),@arrival_at datetime2(0),@booking_cutoff_at datetime2(0),@saleable_teu int,@saleable_gross_kg decimal(14,3),@expected_version varchar(18)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRANSACTION;
  EXEC dbo.usp_AssertRole @actor_id,'ADMIN';
  DECLARE @rv binary(8),@status varchar(12),@before nvarchar(max),@after nvarchar(max),@nominal int;
  IF @voyage_id IS NOT NULL
  BEGIN
   SELECT @rv=row_version,@status=status FROM dbo.Voyage WITH(UPDLOCK,HOLDLOCK) WHERE voyage_id=@voyage_id;
   IF @status IS NULL THROW 50012,N'航次不存在。',1;
   IF @status<>'DRAFT' THROW 50030,N'已发布航次的船舶、港口、时间及配额不可修改。',1;
   IF @expected_version IS NULL OR LEN(@expected_version)<>18 OR TRY_CONVERT(binary(8),@expected_version,1) IS NULL OR TRY_CONVERT(binary(8),@expected_version,1)<>@rv
    THROW 50018,N'数据已被其他操作修改，请刷新后重试。',1;
   SET @before=(SELECT * FROM dbo.Voyage WHERE voyage_id=@voyage_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  END;
  IF NULLIF(LTRIM(RTRIM(@voyage_no)),'') IS NULL THROW 50031,N'航次编号不能为空。',1;
  SELECT @nominal=nominal_teu FROM dbo.Vessel WHERE vessel_id=@vessel_id AND is_active=1;
  IF @nominal IS NULL THROW 50032,N'请选择有效船舶。',1;
  IF NOT EXISTS(SELECT 1 FROM dbo.Port WHERE port_id=@origin_port_id AND is_active=1) OR NOT EXISTS(SELECT 1 FROM dbo.Port WHERE port_id=@destination_port_id AND is_active=1)
   THROW 50033,N'请选择有效起运港与目的港。',1;
  IF @origin_port_id=@destination_port_id THROW 50034,N'起运港和目的港不能相同。',1;
  IF @saleable_teu IS NULL OR @saleable_teu<=0 OR @saleable_teu>@nominal OR @saleable_gross_kg IS NULL OR @saleable_gross_kg<=0
   THROW 50035,N'配额必须为正数，且可售 TEU 不能超过船舶标称容量。',1;
  IF @departure_at IS NULL OR @arrival_at IS NULL OR @booking_cutoff_at IS NULL OR @arrival_at<=@departure_at OR @booking_cutoff_at>@departure_at
   THROW 50036,N'预计到港须晚于离港，截单时间不得晚于离港。',1;
  IF @voyage_id IS NULL
  BEGIN
   INSERT dbo.Voyage(voyage_no,vessel_id,origin_port_id,destination_port_id,departure_at,arrival_at,booking_cutoff_at,saleable_teu,saleable_gross_kg)
    VALUES(LTRIM(RTRIM(@voyage_no)),@vessel_id,@origin_port_id,@destination_port_id,@departure_at,@arrival_at,@booking_cutoff_at,@saleable_teu,@saleable_gross_kg);
   SET @voyage_id=SCOPE_IDENTITY();
  END
  ELSE UPDATE dbo.Voyage SET voyage_no=LTRIM(RTRIM(@voyage_no)),vessel_id=@vessel_id,origin_port_id=@origin_port_id,destination_port_id=@destination_port_id,
   departure_at=@departure_at,arrival_at=@arrival_at,booking_cutoff_at=@booking_cutoff_at,saleable_teu=@saleable_teu,saleable_gross_kg=@saleable_gross_kg WHERE voyage_id=@voyage_id;
  SET @after=(SELECT * FROM dbo.Voyage WHERE voyage_id=@voyage_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  INSERT dbo.AuditLog(actor_user_id,action_code,entity_name,entity_key,before_json,after_json)
   VALUES(@actor_id,CASE WHEN @before IS NULL THEN 'CREATE' ELSE 'UPDATE' END,'Voyage',CONVERT(nvarchar(128),@voyage_id),@before,@after);
  COMMIT;
  SELECT voyage_id,voyage_no,status,row_version,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex FROM dbo.Voyage WHERE voyage_id=@voyage_id;
 END TRY
 BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK;
  THROW;
 END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE dbo.usp_TransitionVoyage
 @actor_id bigint,@voyage_id bigint,@target_status varchar(12),@expected_version varchar(18)=NULL
AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRANSACTION;
  EXEC dbo.usp_AssertRole @actor_id,'ADMIN';
  DECLARE @status varchar(12),@rv binary(8),@cutoff datetime2(0),@before nvarchar(max),@after nvarchar(max);
  SELECT @status=status,@rv=row_version,@cutoff=booking_cutoff_at FROM dbo.Voyage WITH(UPDLOCK,HOLDLOCK) WHERE voyage_id=@voyage_id;
  IF @status IS NULL THROW 50012,N'航次不存在。',1;
  IF @expected_version IS NULL OR LEN(@expected_version)<>18 OR TRY_CONVERT(binary(8),@expected_version,1) IS NULL OR TRY_CONVERT(binary(8),@expected_version,1)<>@rv
   THROW 50018,N'数据已被其他操作修改，请刷新后重试。',1;
  IF @target_status IS NULL OR NOT ((@status='DRAFT' AND @target_status='OPEN') OR (@status='OPEN' AND @target_status='CLOSED') OR
   (@status='CLOSED' AND @target_status='DEPARTED') OR (@status='DEPARTED' AND @target_status='COMPLETED')) THROW 50037,N'航次必须按草稿、开放、关闭、离港、完成依次推进。',1;
  IF @target_status='OPEN'
  BEGIN
   IF @cutoff<=DATEADD(hour,8,SYSUTCDATETIME()) THROW 50038,N'已超过截单时间，不能开放航次。',1;
   IF EXISTS(SELECT 1 FROM dbo.Voyage v JOIN dbo.Vessel s ON s.vessel_id=v.vessel_id JOIN dbo.Port o ON o.port_id=v.origin_port_id JOIN dbo.Port d ON d.port_id=v.destination_port_id
    WHERE v.voyage_id=@voyage_id AND (s.is_active=0 OR o.is_active=0 OR d.is_active=0 OR v.saleable_teu>s.nominal_teu)) THROW 50039,N'发布前请核对有效船舶、港口及舱位配额。',1;
  END;
  IF @target_status='DEPARTED' AND EXISTS(SELECT 1 FROM dbo.Booking WHERE voyage_id=@voyage_id AND status='SUBMITTED')
   THROW 50040,N'该航次仍有待审核订舱，请处理后再离港。',1;
  SET @before=(SELECT * FROM dbo.Voyage WHERE voyage_id=@voyage_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  UPDATE dbo.Voyage SET status=@target_status WHERE voyage_id=@voyage_id;
  SET @after=(SELECT * FROM dbo.Voyage WHERE voyage_id=@voyage_id FOR JSON PATH,WITHOUT_ARRAY_WRAPPER);
  INSERT dbo.AuditLog(actor_user_id,action_code,entity_name,entity_key,before_json,after_json)
   VALUES(@actor_id,'TRANSITION','Voyage',CONVERT(nvarchar(128),@voyage_id),@before,@after);
  COMMIT;
  SELECT voyage_id,voyage_no,status,row_version,CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex FROM dbo.Voyage WHERE voyage_id=@voyage_id;
 END TRY
 BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK;
  THROW;
 END CATCH;
END;
GO
