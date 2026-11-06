-- Read-only examples for SSMS and course defense. Select HarborBooking first.
-- 1. Multi-table joins + capacity filtering: bookable Shanghai sailings.
SELECT voyage_no,origin_name,destination_name,departure_at,remaining_teu,remaining_gross_kg
FROM dbo.v_VoyageCapacity
WHERE status='OPEN' AND booking_cutoff_at>DATEADD(hour,8,SYSUTCDATETIME())
 AND remaining_teu>=2 AND remaining_gross_kg>=1000
ORDER BY departure_at;
GO
-- 2. GROUP BY / HAVING: customers with at least two confirmed bookings.
SELECT customer_id,customer_name,COUNT_BIG(*) confirmed_count,SUM(total_teu) confirmed_teu
FROM dbo.v_Bookings WHERE status='CONFIRMED'
GROUP BY customer_id,customer_name HAVING COUNT_BIG(*)>=2 ORDER BY confirmed_teu DESC;
GO
-- 3. Correlated NOT EXISTS: customers without a confirmed booking.
SELECT c.customer_code,c.customer_name FROM dbo.v_Customers c
WHERE NOT EXISTS(SELECT 1 FROM dbo.v_Bookings b WHERE b.customer_id=c.customer_id AND b.status='CONFIRMED');
GO
-- 4. Calendar CTE + LAG: include zero months before calculating month-on-month change.
DECLARE @start date=DATEFROMPARTS(YEAR(DATEADD(hour,8,SYSUTCDATETIME())),1,1);
;WITH Months AS (
 SELECT @start month_start
 UNION ALL SELECT DATEADD(month,1,month_start) FROM Months WHERE month_start<DATEADD(month,11,@start)
), Totals AS (
 SELECT m.month_start,COUNT_BIG(b.booking_id) confirmed_count,COALESCE(SUM(b.total_teu),0) confirmed_teu
 FROM Months m LEFT JOIN dbo.v_Bookings b ON b.departure_at>=m.month_start
 AND b.departure_at<DATEADD(month,1,m.month_start) AND b.status='CONFIRMED'
 GROUP BY m.month_start
)
SELECT CONVERT(char(7),month_start,126) month,confirmed_count,confirmed_teu,
 confirmed_teu-LAG(confirmed_teu) OVER(ORDER BY month_start) teu_change
FROM Totals ORDER BY month_start OPTION(MAXRECURSION 12);
GO
-- 5. Window function: customer ranking; ties share a rank.
SELECT customer_name,confirmed_bookings,confirmed_teu,
 DENSE_RANK() OVER(ORDER BY confirmed_teu DESC) teu_rank
FROM dbo.v_CustomerStatistics WHERE confirmed_teu>0;
GO
-- 6. Reconciliation: this query must return no rows after successful operations.
SELECT voyage_no,used_teu,saleable_teu,used_gross_kg,saleable_gross_kg
FROM dbo.v_VoyageCapacity WHERE used_teu>saleable_teu OR used_gross_kg>saleable_gross_kg;
GO
