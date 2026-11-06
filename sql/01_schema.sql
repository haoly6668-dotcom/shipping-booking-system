-- Deploy only into the explicitly selected project database. No database creation/deletion.
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
GO
IF OBJECT_ID(N'dbo.Customer', N'U') IS NULL
CREATE TABLE dbo.Customer (
 customer_id bigint IDENTITY CONSTRAINT PK_Customer PRIMARY KEY,
 customer_code varchar(20) NOT NULL CONSTRAINT UQ_Customer_Code UNIQUE,
 customer_name nvarchar(100) NOT NULL, contact_name nvarchar(50) NOT NULL,
 contact_phone varchar(30) NOT NULL, email nvarchar(254) NULL,
 is_active bit NOT NULL CONSTRAINT DF_Customer_Active DEFAULT 1,
 created_at datetime2(0) NOT NULL CONSTRAINT DF_Customer_Created DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 row_version rowversion NOT NULL,
 CONSTRAINT CK_Customer_Required CHECK (LEN(LTRIM(RTRIM(customer_code)))>0 AND LEN(LTRIM(RTRIM(customer_name)))>0 AND LEN(LTRIM(RTRIM(contact_name)))>0 AND LEN(LTRIM(RTRIM(contact_phone)))>0)
);
IF OBJECT_ID(N'dbo.Port', N'U') IS NULL
CREATE TABLE dbo.Port (
 port_id int IDENTITY CONSTRAINT PK_Port PRIMARY KEY,
 port_code varchar(10) NOT NULL CONSTRAINT UQ_Port_Code UNIQUE,
 port_name nvarchar(100) NOT NULL, country_region nvarchar(60) NOT NULL,
 is_active bit NOT NULL CONSTRAINT DF_Port_Active DEFAULT 1,
 row_version rowversion NOT NULL,
 CONSTRAINT CK_Port_Required CHECK (LEN(LTRIM(RTRIM(port_code)))>0 AND LEN(LTRIM(RTRIM(port_name)))>0 AND LEN(LTRIM(RTRIM(country_region)))>0)
);
IF OBJECT_ID(N'dbo.Vessel', N'U') IS NULL
CREATE TABLE dbo.Vessel (
 vessel_id int IDENTITY CONSTRAINT PK_Vessel PRIMARY KEY,
 vessel_code varchar(20) NOT NULL CONSTRAINT UQ_Vessel_Code UNIQUE,
 vessel_name nvarchar(100) NOT NULL, nominal_teu int NOT NULL,
 is_active bit NOT NULL CONSTRAINT DF_Vessel_Active DEFAULT 1,
 row_version rowversion NOT NULL,
 CONSTRAINT CK_Vessel_Required CHECK (LEN(LTRIM(RTRIM(vessel_code)))>0 AND LEN(LTRIM(RTRIM(vessel_name)))>0 AND nominal_teu>0)
);
IF OBJECT_ID(N'dbo.AppUser', N'U') IS NULL
CREATE TABLE dbo.AppUser (
 user_id bigint IDENTITY CONSTRAINT PK_AppUser PRIMARY KEY,
 username nvarchar(50) COLLATE Chinese_PRC_CI_AS NOT NULL CONSTRAINT UQ_AppUser_Username UNIQUE,
 display_name nvarchar(50) NOT NULL, password_hash varchar(512) NOT NULL,
 is_active bit NOT NULL CONSTRAINT DF_AppUser_Active DEFAULT 1,
 created_at datetime2(0) NOT NULL CONSTRAINT DF_AppUser_Created DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 row_version rowversion NOT NULL,
 CONSTRAINT CK_AppUser_Required CHECK (LEN(LTRIM(RTRIM(username)))>0 AND LEN(LTRIM(RTRIM(display_name)))>0 AND LEN(password_hash)>0)
);
IF OBJECT_ID(N'dbo.Role', N'U') IS NULL
CREATE TABLE dbo.[Role] (
 role_id int IDENTITY CONSTRAINT PK_Role PRIMARY KEY,
 role_code varchar(30) NOT NULL CONSTRAINT UQ_Role_Code UNIQUE,
 role_name nvarchar(50) NOT NULL, description nvarchar(200) NULL,
 CONSTRAINT CK_Role_Code CHECK (role_code IN ('ADMIN','SALES','REVIEWER','ANALYST'))
);
IF OBJECT_ID(N'dbo.UserRole', N'U') IS NULL
CREATE TABLE dbo.UserRole (
 user_id bigint NOT NULL, role_id int NOT NULL, assigned_by bigint NOT NULL,
 assigned_at datetime2(0) NOT NULL CONSTRAINT DF_UserRole_Assigned DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 CONSTRAINT PK_UserRole PRIMARY KEY(user_id,role_id),
 CONSTRAINT FK_UserRole_User FOREIGN KEY(user_id) REFERENCES dbo.AppUser(user_id),
 CONSTRAINT FK_UserRole_Role FOREIGN KEY(role_id) REFERENCES dbo.[Role](role_id),
 CONSTRAINT FK_UserRole_Assigner FOREIGN KEY(assigned_by) REFERENCES dbo.AppUser(user_id)
);
IF OBJECT_ID(N'dbo.Voyage', N'U') IS NULL
CREATE TABLE dbo.Voyage (
 voyage_id bigint IDENTITY CONSTRAINT PK_Voyage PRIMARY KEY,
 voyage_no varchar(30) NOT NULL CONSTRAINT UQ_Voyage_No UNIQUE,
 vessel_id int NOT NULL, origin_port_id int NOT NULL, destination_port_id int NOT NULL,
 departure_at datetime2(0) NOT NULL, arrival_at datetime2(0) NOT NULL, booking_cutoff_at datetime2(0) NOT NULL,
 saleable_teu int NOT NULL, saleable_gross_kg decimal(14,3) NOT NULL,
 status varchar(12) NOT NULL CONSTRAINT DF_Voyage_Status DEFAULT 'DRAFT',
 created_at datetime2(0) NOT NULL CONSTRAINT DF_Voyage_Created DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 row_version rowversion NOT NULL,
 CONSTRAINT FK_Voyage_Vessel FOREIGN KEY(vessel_id) REFERENCES dbo.Vessel(vessel_id),
 CONSTRAINT FK_Voyage_Origin FOREIGN KEY(origin_port_id) REFERENCES dbo.Port(port_id),
 CONSTRAINT FK_Voyage_Destination FOREIGN KEY(destination_port_id) REFERENCES dbo.Port(port_id),
 CONSTRAINT CK_Voyage_No CHECK (LEN(LTRIM(RTRIM(voyage_no)))>0),
 CONSTRAINT CK_Voyage_Ports CHECK (origin_port_id<>destination_port_id),
 CONSTRAINT CK_Voyage_Time CHECK (arrival_at>departure_at AND booking_cutoff_at<=departure_at),
 CONSTRAINT CK_Voyage_Quota CHECK (saleable_teu>0 AND saleable_gross_kg>0),
 CONSTRAINT CK_Voyage_Status CHECK (status IN ('DRAFT','OPEN','CLOSED','DEPARTED','COMPLETED'))
);
IF OBJECT_ID(N'dbo.ContainerType', N'U') IS NULL
CREATE TABLE dbo.ContainerType (
 container_type_id tinyint CONSTRAINT PK_ContainerType PRIMARY KEY,
 type_code varchar(4) NOT NULL CONSTRAINT UQ_ContainerType_Code UNIQUE,
 type_name nvarchar(40) NOT NULL, teu_factor tinyint NOT NULL,
 CONSTRAINT CK_ContainerType_Factor CHECK ((type_code='20GP' AND teu_factor=1) OR (type_code IN ('40GP','40HQ') AND teu_factor=2))
);
IF OBJECT_ID(N'dbo.Booking', N'U') IS NULL
CREATE TABLE dbo.Booking (
 booking_id bigint IDENTITY CONSTRAINT PK_Booking PRIMARY KEY,
 booking_no varchar(30) NOT NULL CONSTRAINT UQ_Booking_No UNIQUE,
 customer_id bigint NOT NULL, voyage_id bigint NOT NULL,
 status varchar(12) NOT NULL CONSTRAINT DF_Booking_Status DEFAULT 'DRAFT',
 cargo_description nvarchar(200) NOT NULL, remark nvarchar(500) NULL,
 created_by bigint NOT NULL,
 created_at datetime2(0) NOT NULL CONSTRAINT DF_Booking_Created DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 updated_at datetime2(0) NOT NULL CONSTRAINT DF_Booking_Updated DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 last_changed_by bigint NOT NULL, status_reason nvarchar(500) NULL, row_version rowversion NOT NULL,
 CONSTRAINT FK_Booking_Customer FOREIGN KEY(customer_id) REFERENCES dbo.Customer(customer_id),
 CONSTRAINT FK_Booking_Voyage FOREIGN KEY(voyage_id) REFERENCES dbo.Voyage(voyage_id),
 CONSTRAINT FK_Booking_Creator FOREIGN KEY(created_by) REFERENCES dbo.AppUser(user_id),
 CONSTRAINT FK_Booking_Actor FOREIGN KEY(last_changed_by) REFERENCES dbo.AppUser(user_id),
 CONSTRAINT CK_Booking_Status CHECK (status IN ('DRAFT','SUBMITTED','CONFIRMED','REJECTED','CANCELLED')),
 CONSTRAINT CK_Booking_Required CHECK (LEN(LTRIM(RTRIM(booking_no)))>0 AND LEN(LTRIM(RTRIM(cargo_description)))>0),
 CONSTRAINT CK_Booking_Time CHECK (updated_at>=created_at)
);
IF OBJECT_ID(N'dbo.BookingItem', N'U') IS NULL
CREATE TABLE dbo.BookingItem (
 booking_id bigint NOT NULL, container_type_id tinyint NOT NULL,
 quantity int NOT NULL, total_gross_kg decimal(14,3) NOT NULL,
 CONSTRAINT PK_BookingItem PRIMARY KEY(booking_id,container_type_id),
 CONSTRAINT FK_BookingItem_Booking FOREIGN KEY(booking_id) REFERENCES dbo.Booking(booking_id),
 CONSTRAINT FK_BookingItem_Type FOREIGN KEY(container_type_id) REFERENCES dbo.ContainerType(container_type_id),
 CONSTRAINT CK_BookingItem_Positive CHECK (quantity>0 AND total_gross_kg>0)
);
IF OBJECT_ID(N'dbo.BookingStatusHistory', N'U') IS NULL
CREATE TABLE dbo.BookingStatusHistory (
 history_id bigint IDENTITY CONSTRAINT PK_BookingStatusHistory PRIMARY KEY,
 booking_id bigint NOT NULL, from_status varchar(12) NULL, to_status varchar(12) NOT NULL,
 changed_by bigint NOT NULL,
 changed_at datetime2(0) NOT NULL CONSTRAINT DF_BookingHistory_Time DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 reason nvarchar(500) NULL,
 CONSTRAINT FK_BookingHistory_Booking FOREIGN KEY(booking_id) REFERENCES dbo.Booking(booking_id),
 CONSTRAINT FK_BookingHistory_Actor FOREIGN KEY(changed_by) REFERENCES dbo.AppUser(user_id),
 CONSTRAINT CK_BookingHistory_From CHECK (from_status IS NULL OR from_status IN ('DRAFT','SUBMITTED','CONFIRMED','REJECTED','CANCELLED')),
 CONSTRAINT CK_BookingHistory_To CHECK (to_status IN ('DRAFT','SUBMITTED','CONFIRMED','REJECTED','CANCELLED')),
 CONSTRAINT CK_BookingHistory_Change CHECK ((from_status IS NULL AND to_status='DRAFT') OR (from_status IS NOT NULL AND from_status<>to_status))
);
IF OBJECT_ID(N'dbo.AuditLog', N'U') IS NULL
CREATE TABLE dbo.AuditLog (
 audit_id bigint IDENTITY CONSTRAINT PK_AuditLog PRIMARY KEY,
 actor_user_id bigint NOT NULL, action_code varchar(30) NOT NULL,
 entity_name varchar(64) NOT NULL, entity_key nvarchar(128) NOT NULL,
 before_json nvarchar(max) NULL, after_json nvarchar(max) NULL,
 occurred_at datetime2(0) NOT NULL CONSTRAINT DF_AuditLog_Time DEFAULT DATEADD(hour,8,SYSUTCDATETIME()),
 request_id uniqueidentifier NOT NULL CONSTRAINT DF_AuditLog_Request DEFAULT NEWID(),
 CONSTRAINT FK_AuditLog_Actor FOREIGN KEY(actor_user_id) REFERENCES dbo.AppUser(user_id),
 CONSTRAINT CK_AuditLog_Before CHECK (before_json IS NULL OR ISJSON(before_json)=1),
 CONSTRAINT CK_AuditLog_After CHECK (after_json IS NULL OR ISJSON(after_json)=1),
 CONSTRAINT CK_AuditLog_Snapshot CHECK (before_json IS NOT NULL OR after_json IS NOT NULL),
 CONSTRAINT CK_AuditLog_Required CHECK (LEN(action_code)>0 AND LEN(entity_name)>0 AND LEN(entity_key)>0)
);
GO
IF OBJECT_ID(N'dbo.BookingNumber', N'SO') IS NULL EXEC(N'CREATE SEQUENCE dbo.BookingNumber AS bigint START WITH 1 INCREMENT BY 1 NO CYCLE');
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.Booking') AND name=N'IX_Booking_VoyageStatus')
 CREATE INDEX IX_Booking_VoyageStatus ON dbo.Booking(voyage_id,status) INCLUDE(customer_id,created_at,booking_no);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.Booking') AND name=N'IX_Booking_CustomerDate')
 CREATE INDEX IX_Booking_CustomerDate ON dbo.Booking(customer_id,created_at DESC) INCLUDE(voyage_id,status);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.Booking') AND name=N'IX_Booking_CreatorDate')
 CREATE INDEX IX_Booking_CreatorDate ON dbo.Booking(created_by,created_at DESC) INCLUDE(voyage_id,status);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.Voyage') AND name=N'IX_Voyage_RouteDate')
 CREATE INDEX IX_Voyage_RouteDate ON dbo.Voyage(origin_port_id,destination_port_id,departure_at) INCLUDE(status,saleable_teu);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.BookingStatusHistory') AND name=N'IX_BookingHistory_Order')
 CREATE INDEX IX_BookingHistory_Order ON dbo.BookingStatusHistory(booking_id,history_id);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.BookingStatusHistory') AND name=N'UX_BookingHistory_Initial')
 CREATE UNIQUE INDEX UX_BookingHistory_Initial ON dbo.BookingStatusHistory(booking_id) WHERE from_status IS NULL;
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.UserRole') AND name=N'IX_UserRole_RoleUser')
 CREATE INDEX IX_UserRole_RoleUser ON dbo.UserRole(role_id,user_id);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.AuditLog') AND name=N'IX_AuditLog_Entity')
 CREATE INDEX IX_AuditLog_Entity ON dbo.AuditLog(entity_name,entity_key,occurred_at DESC);
GO
INSERT dbo.[Role](role_code,role_name,description)
SELECT x.code,x.name,x.description FROM (VALUES
 ('ADMIN',N'系统管理员',N'账户权限、主数据、航次及审计管理'),
 ('SALES',N'订舱业务员',N'本人订舱单创建、提交、修订及取消'),
 ('REVIEWER',N'订舱审核员',N'他人提交的订舱确认及驳回'),
 ('ANALYST',N'统计分析员',N'统计报表只读访问')
)x(code,name,description) WHERE NOT EXISTS(SELECT 1 FROM dbo.[Role] r WHERE r.role_code=x.code);
INSERT dbo.ContainerType(container_type_id,type_code,type_name,teu_factor)
SELECT x.id,x.code,x.name,x.factor FROM (VALUES (1,'20GP',N'20英尺普通箱',1),(2,'40GP',N'40英尺普通箱',2),(3,'40HQ',N'40英尺高箱',2))x(id,code,name,factor)
WHERE NOT EXISTS(SELECT 1 FROM dbo.ContainerType c WHERE c.container_type_id=x.id);
GO
