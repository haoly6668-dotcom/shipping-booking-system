SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO
CREATE OR ALTER VIEW dbo.v_Customers AS
SELECT c.*, CONVERT(varchar(18),CONVERT(binary(8),c.row_version),1) version_hex FROM dbo.Customer c;
GO
CREATE OR ALTER VIEW dbo.v_Ports AS
SELECT p.*, CONVERT(varchar(18),CONVERT(binary(8),p.row_version),1) version_hex FROM dbo.Port p;
GO
CREATE OR ALTER VIEW dbo.v_Vessels AS
SELECT v.*, CONVERT(varchar(18),CONVERT(binary(8),v.row_version),1) version_hex FROM dbo.Vessel v;
GO
CREATE OR ALTER VIEW dbo.v_ContainerTypes AS SELECT * FROM dbo.ContainerType;
GO
CREATE OR ALTER VIEW dbo.v_Roles AS SELECT * FROM dbo.[Role];
GO
CREATE OR ALTER VIEW dbo.v_Users AS
SELECT user_id,username,display_name,is_active,created_at,row_version,
 CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version_hex FROM dbo.AppUser;
GO
CREATE OR ALTER VIEW dbo.v_UserRoles AS
SELECT ur.user_id,ur.role_id,r.role_code,r.role_name FROM dbo.UserRole ur JOIN dbo.[Role] r ON r.role_id=ur.role_id;
GO
CREATE OR ALTER VIEW dbo.v_BookingItems AS
SELECT i.*,c.type_code,c.type_name,c.teu_factor FROM dbo.BookingItem i JOIN dbo.ContainerType c ON c.container_type_id=i.container_type_id;
GO
CREATE OR ALTER VIEW dbo.v_Bookings AS
SELECT b.*,c.customer_name,v.voyage_no,o.port_name origin_name,d.port_name destination_name,
 v.departure_at,v.status voyage_status,u.display_name creator_name,
 COALESCE(a.total_boxes,0) total_boxes,COALESCE(a.total_teu,0) total_teu,
 COALESCE(a.total_gross_kg,CONVERT(decimal(38,3),0)) total_gross_kg,
 CONVERT(varchar(18),CONVERT(binary(8),b.row_version),1) version_hex
FROM dbo.Booking b
JOIN dbo.Customer c ON c.customer_id=b.customer_id
JOIN dbo.Voyage v ON v.voyage_id=b.voyage_id
JOIN dbo.Port o ON o.port_id=v.origin_port_id
JOIN dbo.Port d ON d.port_id=v.destination_port_id
JOIN dbo.AppUser u ON u.user_id=b.created_by
OUTER APPLY (SELECT SUM(CONVERT(bigint,i.quantity)) total_boxes,
 SUM(CONVERT(bigint,i.quantity)*t.teu_factor) total_teu,SUM(i.total_gross_kg) total_gross_kg
 FROM dbo.BookingItem i JOIN dbo.ContainerType t ON t.container_type_id=i.container_type_id WHERE i.booking_id=b.booking_id) a;
GO
CREATE OR ALTER VIEW dbo.v_VoyageCapacity AS
SELECT v.*,o.port_name origin_name,d.port_name destination_name,s.vessel_name,s.nominal_teu,
 COALESCE(a.used_teu,0) used_teu,COALESCE(a.used_gross_kg,CONVERT(decimal(38,3),0)) used_gross_kg,
 v.saleable_teu-COALESCE(a.used_teu,0) remaining_teu,
 v.saleable_gross_kg-COALESCE(a.used_gross_kg,0) remaining_gross_kg,
 CONVERT(decimal(10,2),COALESCE(a.used_teu,0)*100.0/NULLIF(v.saleable_teu,0)) utilization_pct,
 CONVERT(varchar(18),CONVERT(binary(8),v.row_version),1) version_hex
FROM dbo.Voyage v JOIN dbo.Vessel s ON s.vessel_id=v.vessel_id
JOIN dbo.Port o ON o.port_id=v.origin_port_id JOIN dbo.Port d ON d.port_id=v.destination_port_id
OUTER APPLY (SELECT SUM(CONVERT(bigint,i.quantity)*t.teu_factor) used_teu,SUM(i.total_gross_kg) used_gross_kg
 FROM dbo.Booking b JOIN dbo.BookingItem i ON i.booking_id=b.booking_id
 JOIN dbo.ContainerType t ON t.container_type_id=i.container_type_id
 WHERE b.voyage_id=v.voyage_id AND b.status='CONFIRMED') a;
GO
CREATE OR ALTER VIEW dbo.v_BookingHistory AS
SELECT h.*,u.display_name FROM dbo.BookingStatusHistory h JOIN dbo.AppUser u ON u.user_id=h.changed_by;
GO
CREATE OR ALTER VIEW dbo.v_Audit AS
SELECT a.*,u.display_name FROM dbo.AuditLog a JOIN dbo.AppUser u ON u.user_id=a.actor_user_id;
GO
CREATE OR ALTER VIEW dbo.v_CustomerStatistics AS
SELECT c.customer_id,c.customer_code,c.customer_name,COUNT_BIG(b.booking_id) total_bookings,
 SUM(CASE WHEN b.status='CONFIRMED' THEN CONVERT(bigint,1) ELSE 0 END) confirmed_bookings,
 SUM(CASE WHEN b.status='CONFIRMED' THEN b.total_boxes ELSE 0 END) confirmed_boxes,
 SUM(CASE WHEN b.status='CONFIRMED' THEN b.total_teu ELSE 0 END) confirmed_teu,
 SUM(CASE WHEN b.status='CONFIRMED' THEN b.total_gross_kg ELSE 0 END) confirmed_gross_kg
FROM dbo.Customer c LEFT JOIN dbo.v_Bookings b ON b.customer_id=c.customer_id
GROUP BY c.customer_id,c.customer_code,c.customer_name;
GO
CREATE OR ALTER VIEW dbo.v_VoyageManifest AS
SELECT b.voyage_id,v.voyage_no,b.booking_id,b.booking_no,b.customer_id,c.customer_name,
 i.container_type_id,t.type_code,i.quantity,CONVERT(bigint,i.quantity)*t.teu_factor teu,i.total_gross_kg
FROM dbo.Booking b JOIN dbo.Voyage v ON v.voyage_id=b.voyage_id JOIN dbo.Customer c ON c.customer_id=b.customer_id
JOIN dbo.BookingItem i ON i.booking_id=b.booking_id JOIN dbo.ContainerType t ON t.container_type_id=i.container_type_id
WHERE b.status='CONFIRMED';
GO
-- Set-based: every inserted/status-changed row receives exactly one history record.
CREATE OR ALTER TRIGGER dbo.trg_BookingStatusHistory ON dbo.Booking AFTER INSERT,UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted i LEFT JOIN deleted d ON d.booking_id=i.booking_id WHERE d.booking_id IS NULL AND i.status<>'DRAFT')
  THROW 50070,N'新订舱必须从草稿开始。',1;
 IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON d.booking_id=i.booking_id WHERE i.voyage_id<>d.voyage_id OR i.created_by<>d.created_by)
  THROW 50071,N'订舱创建后不可变更航次或创建人。',1;
 IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON d.booking_id=i.booking_id WHERE i.status<>d.status AND NOT
   ((d.status='DRAFT' AND i.status IN ('SUBMITTED','CANCELLED')) OR
    (d.status='SUBMITTED' AND i.status IN ('DRAFT','CONFIRMED','REJECTED','CANCELLED')) OR
    (d.status='REJECTED' AND i.status IN ('DRAFT','CANCELLED')) OR
    (d.status='CONFIRMED' AND i.status='CANCELLED')))
  THROW 50072,N'不允许该订舱状态转换。',1;
 INSERT dbo.BookingStatusHistory(booking_id,from_status,to_status,changed_by,reason)
 SELECT i.booking_id,d.status,i.status,i.last_changed_by,i.status_reason
 FROM inserted i LEFT JOIN deleted d ON d.booking_id=i.booking_id
 WHERE d.booking_id IS NULL OR i.status<>d.status;
END;
GO
CREATE OR ALTER TRIGGER dbo.trg_BookingItemGuard ON dbo.BookingItem AFTER INSERT,UPDATE,DELETE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM dbo.Booking b JOIN (SELECT booking_id FROM inserted UNION SELECT booking_id FROM deleted) x ON x.booking_id=b.booking_id WHERE b.status<>'DRAFT')
  THROW 50073,N'只有草稿订舱可以修改箱型明细。',1;
END;
GO
