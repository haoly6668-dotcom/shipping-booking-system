import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from .db import repo, BusinessError

BEIJING = timezone(timedelta(hours=8))
def now():
    return datetime.now(BEIJING).replace(tzinfo=None)

def text_value(form, key, limit, required=True):
    value = str(form.get(key, '')).strip()
    if required and not value:
        raise BusinessError(f'请填写 {key}。', 400)
    if len(value) > limit:
        raise BusinessError(f'{key} 最多允许 {limit} 个字符。', 400)
    return value or None

def integer(value, label='编号', optional=False, maximum=2147483647):
    if optional and value in (None, ''):
        return None
    if not re.fullmatch(r'\d+', str(value or '')):
        raise BusinessError(f'{label} 必须是正整数。', 400)
    number = int(value)
    if number < 1 or number > maximum:
        raise BusinessError(f'{label} 超出允许范围。', 400)
    return number

def weight(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number >= Decimal('100000000000'):
            raise ValueError()
        if number.as_tuple().exponent < -3:
            raise ValueError()
        return str(number)
    except (InvalidOperation, ValueError):
        raise BusinessError('总毛重须为正数，最多三位小数，且小于一千亿 kg。',400)

def version(value, required=False):
    if not value and not required:
        return None
    if not re.fullmatch(r'0x[0-9a-fA-F]{16}', str(value or '')):
        raise BusinessError('缺少有效的数据版本，请刷新页面重试。',409)
    return value

def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo or result.year < 2000 or result.year > 2100:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise BusinessError('日期时间格式不正确，须在 2000 至 2100 年之间。',400)

def date_range(args):
    def parse(key):
        value = args.get(key)
        if not value:return None
        try:
            result=datetime.strptime(value,'%Y-%m-%d')
            if not 2000<=result.year<=2100:raise ValueError()
            return result
        except ValueError:raise BusinessError('日期格式应为 YYYY-MM-DD。',400)
    start,end = parse('date_from'),parse('date_to')
    if start and end and start>end:raise BusinessError('开始日期不能晚于结束日期。',400)
    return start, end+timedelta(days=1) if end else None


class BookingService:
    def save(self, actor, form, booking_id=None):
        ids, quantities, weights = [form.getlist(k) for k in ('container_type_id','quantity','total_gross_kg')]
        if not len(ids)==len(quantities)==len(weights) or len(ids)>3:
            raise BusinessError('明细格式不正确，最多可填写三个不同箱型。',400)
        items=[];seen=set()
        for ct,q,w in zip(ids,quantities,weights):
            if not any([ct,q,w]):continue
            ct=integer(ct,'箱型',maximum=3)
            if ct in seen:raise BusinessError('同一个箱型只能填写一行，请合并数量。',400)
            seen.add(ct)
            items.append({'container_type_id':ct,'quantity':integer(q,'箱数'),'total_gross_kg':weight(w)})
        result=repo.procedure('usp_SaveBookingDraft',actor_id=actor,booking_id=booking_id,
            customer_id=integer(form.get('customer_id'),'客户'),voyage_id=integer(form.get('voyage_id'),'航次'),
            cargo_description=text_value(form,'cargo_description',200),remark=text_value(form,'remark',500,False),
            items_json=json.dumps(items,ensure_ascii=False),expected_version=version(form.get('expected_version'),booking_id is not None))
        return result[0] if result else {'booking_id':booking_id}

    def action(self,actor,booking_id,form):
        action=form.get('action','')
        if action not in {'submit','withdraw','reopen','confirm','reject','cancel'}:
            raise BusinessError('未知订舱操作。',400)
        return repo.procedure('usp_BookingAction',actor_id=actor,booking_id=booking_id,action=action,
                reason=text_value(form,'reason',500,action in {'reject','cancel'}),
                expected_version=version(form.get('expected_version'),True))


class VoyageService:
    def save(self, actor, form, voyage_id=None):
        return repo.procedure('usp_SaveVoyage',actor_id=actor,voyage_id=voyage_id,
            voyage_no=text_value(form,'voyage_no',30),vessel_id=integer(form.get('vessel_id'),'船舶'),
            origin_port_id=integer(form.get('origin_port_id'),'起运港'),destination_port_id=integer(form.get('destination_port_id'),'目的港'),
            departure_at=timestamp(form.get('departure_at')),arrival_at=timestamp(form.get('arrival_at')),
            booking_cutoff_at=timestamp(form.get('booking_cutoff_at')),saleable_teu=integer(form.get('saleable_teu'),'可售 TEU'),
            saleable_gross_kg=weight(form.get('saleable_gross_kg')),
            expected_version=version(form.get('expected_version'),voyage_id is not None))


class ReportService:
    def data(self,args):
        start,end=date_range(args)
        cond=[];params=[]
        for op,d in [('>=',start),('<',end)]:
            if d:cond.append('departure_at '+op+' ?');params.append(d)
        where=' AND '.join(cond) or '1=1'
        booking_where='status=\'CONFIRMED\' AND '+where
        summary=repo.one('SELECT COUNT_BIG(*) confirmed_bookings, COALESCE(SUM(total_teu),0) total_teu, COALESCE(SUM(total_gross_kg),0) total_gross_kg FROM dbo.v_Bookings WHERE '+booking_where,params)
        util=repo.one('SELECT COALESCE(SUM(used_teu)*100.0/NULLIF(SUM(CAST(saleable_teu AS bigint)),0),0) utilization_pct FROM dbo.v_VoyageCapacity WHERE '+where,params)
        summary.update(util)
        monthly=repo.query("SELECT CONVERT(char(7),departure_at,126) month, COUNT_BIG(*) booking_count, SUM(total_teu) total_teu, SUM(total_gross_kg) total_gross_kg FROM dbo.v_Bookings WHERE "+booking_where+" GROUP BY CONVERT(char(7),departure_at,126) ORDER BY month",params)
        # Fill absent months before LAG-like change reporting, rather than skipping them.
        if start or end or monthly:
            first=(start or (datetime.strptime(monthly[0]['month'],'%Y-%m') if monthly else end-timedelta(days=1))).replace(day=1,hour=0,minute=0,second=0)
            last=((end-timedelta(days=1)) if end else (datetime.strptime(monthly[-1]['month'],'%Y-%m') if monthly else first)).replace(day=1)
            if (last.year-first.year)*12+last.month-first.month>120:
                raise BusinessError('报表日期范围请控制在十年以内。',400)
            indexed={r['month']:r for r in monthly};monthly=[];cursor=first;previous=None
            while cursor<=last:
                key=cursor.strftime('%Y-%m');row=indexed.get(key,{'month':key,'booking_count':0,'total_teu':0,'total_gross_kg':0})
                row['teu_change']=None if previous is None else row['total_teu']-previous
                monthly.append(row);previous=row['total_teu'];cursor=cursor.replace(year=cursor.year+1,month=1) if cursor.month==12 else cursor.replace(month=cursor.month+1)
        customers=repo.query('SELECT customer_id,customer_name,COUNT_BIG(*) booking_count,SUM(total_teu) total_teu,SUM(total_gross_kg) total_gross_kg FROM dbo.v_Bookings WHERE '+booking_where+' GROUP BY customer_id,customer_name ORDER BY total_teu DESC,customer_id',params)
        routes=repo.query('SELECT origin_name origin_port_name,destination_name destination_port_name,COUNT_BIG(*) voyage_count,SUM(used_teu) used_teu,SUM(CAST(saleable_teu AS bigint)) saleable_teu,SUM(used_teu)*100.0/NULLIF(SUM(CAST(saleable_teu AS bigint)),0) utilization_pct FROM dbo.v_VoyageCapacity WHERE '+where+' GROUP BY origin_name,destination_name ORDER BY used_teu DESC',params)
        inactive=repo.query('SELECT c.customer_code,c.customer_name FROM dbo.v_Customers c WHERE NOT EXISTS (SELECT 1 FROM dbo.v_Bookings b WHERE b.customer_id=c.customer_id AND '+booking_where+') ORDER BY c.customer_code',params)
        return dict(summary=summary,monthly_stats=monthly,customer_stats=customers,route_stats=routes,inactive_customers=inactive)

    def csv(self, rows, fields):
        buffer=io.StringIO(newline='');writer=csv.writer(buffer)
        writer.writerow([label for _,label in fields])
        for row in rows:
            values=[]
            for key,_ in fields:
                value=row.get(key,'')
                # Spreadsheet formula injection protection on exported text.
                if isinstance(value,str) and value[:1] in ('=','+','-','@','\t','\r'):
                    value="'"+value
                values.append(value)
            writer.writerow(values)
        return '\ufeff'+buffer.getvalue()
