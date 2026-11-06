"""Create a NEW isolated course-project database; never drop or reset existing data."""
import argparse
import json
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pyodbc
from werkzeug.security import generate_password_hash

ROOT=Path(__file__).resolve().parents[1]
DEMO_PASSWORD='Harbor@2026'
ROLES=[('ADMIN','系统管理员'),('SALES','订舱业务员'),('REVIEWER','订舱审核员'),('ANALYST','经营分析员')]

def brace(value):return '{'+str(value).replace('}','}}')+'}'
def connect(server,database='master'):
    return pyodbc.connect(f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={brace(server)};DATABASE={brace(database)};Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes',autocommit=True,timeout=10)
def rows(cursor):
    output=[]
    while True:
        if cursor.description:output=[dict(zip([x[0] for x in cursor.description],row)) for row in cursor.fetchall()]
        if not cursor.nextset():break
    return output
def call(conn,name,**params):
    return rows(conn.cursor().execute('EXEC dbo.'+name+' '+','.join('@'+k+'=?' for k in params),tuple(params.values())))
def rv(conn,table,idcol,record_id):
    return conn.execute(f'SELECT CONVERT(varchar(18),CONVERT(binary(8),row_version),1) FROM dbo.[{table}] WHERE {idcol}=?',record_id).fetchone()[0]
def action(conn,user,booking,act,reason=None):
    return call(conn,'usp_BookingAction',actor_id=user,booking_id=booking,action=act,reason=reason,expected_version=rv(conn,'Booking','booking_id',booking))
def draft(conn,user,customer,voyage,items,remark='教学模拟订单'):
    return call(conn,'usp_SaveBookingDraft',actor_id=user,booking_id=None,customer_id=customer,voyage_id=voyage,cargo_description='普通日用品',remark=remark,items_json=json.dumps(items,ensure_ascii=False),expected_version=None)[0]['booking_id']

def seed(conn):
    clock=datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None,microsecond=0)
    # Bootstrap is the only direct user/role write. All business data follows procedures.
    for code,name in ROLES:
        conn.execute('IF NOT EXISTS(SELECT 1 FROM dbo.[Role] WHERE role_code=?) INSERT dbo.[Role](role_code,role_name,description) VALUES(?,?,?)',code,code,name,name+'教学演示角色')
    admin=conn.execute('INSERT dbo.AppUser(username,display_name,password_hash,is_active,created_at) OUTPUT inserted.user_id VALUES(?,?,?,?,?)','admin','系统管理员',generate_password_hash(DEMO_PASSWORD),1,clock).fetchone()[0]
    conn.execute("INSERT dbo.UserRole(user_id,role_id,assigned_by,assigned_at) SELECT ?,role_id,?,? FROM dbo.[Role] WHERE role_code='ADMIN'",admin,admin,clock)
    accounts={'admin':admin}
    for username,name,roles in [('sales','订舱专员 林舟',['SALES']),('sales2','订舱专员 陈海',['SALES']),('reviewer','审核员 周宁',['REVIEWER']),('analyst','经营分析员 顾澜',['ANALYST'])]:
        accounts[username]=call(conn,'usp_SaveUser',actor_id=admin,user_id=None,username=username,display_name=name,password_hash=generate_password_hash(DEMO_PASSWORD),is_active=True,roles_json=json.dumps(roles),expected_version=None)[0]['user_id']
    ports=[]
    for code,name,country in [('SHA','上海','中国'),('NGB','宁波','中国'),('SZX','深圳','中国'),('TAO','青岛','中国'),('SIN','新加坡','新加坡'),('PUS','釜山','韩国'),('YOK','横滨','日本'),('RTM','鹿特丹','荷兰')]:
        ports.append(call(conn,'usp_MasterData',actor_id=admin,entity='Port',action='save',id=None,data_json=json.dumps(dict(port_code=code,port_name=name,country_region=country,is_active=1),ensure_ascii=False),expected_version=None)[0]['id'])
    vessels=[]
    for index,name in enumerate(['海澜远航','东海之星','海事先锋','蓝湾信使','远洋明珠','浦江晨光'],1):
        vessels.append(call(conn,'usp_MasterData',actor_id=admin,entity='Vessel',action='save',id=None,data_json=json.dumps(dict(vessel_code=f'SHIP-{index:02}',vessel_name=name,nominal_teu=1000+index*500,is_active=1),ensure_ascii=False),expected_version=None)[0]['id'])
    customers=[]
    for index,name in enumerate(['海帆贸易','浦江电器','远东纺织','晨光家居','蓝港制造','新航电子','东岸商贸','明洲供应链','中洋设备','海桥日用','南湾箱包','海聚建材','江海机械','清风文具','启航照明','百川出口','华澜五金','晨曦塑料','星港食品','安海商贸'],1):
        customers.append(call(conn,'usp_MasterData',actor_id=admin,entity='Customer',action='save',id=None,data_json=json.dumps(dict(customer_code=f'C{index:04}',customer_name=name+'有限公司',contact_name='模拟联系人',contact_phone=f'1380000{index:04}',email=f'customer{index}@example.test',is_active=1),ensure_ascii=False),expected_version=None)[0]['id'])
    # Fixed concurrency baseline, independent of the larger display data.
    voyage_ids=[]
    for index in range(24):
        origin=ports[index%4];destination=ports[4+index%4]
        departure=clock+timedelta(days=12+index*4)
        saved=call(conn,'usp_SaveVoyage',actor_id=admin,voyage_id=None,voyage_no='DEMO-001' if index==0 else f'SMU-{index:03}',vessel_id=vessels[index%6],origin_port_id=origin,destination_port_id=destination,departure_at=departure,arrival_at=departure+timedelta(days=5+index%10),booking_cutoff_at=departure-timedelta(days=2),saleable_teu=10 if index==0 else 60+index*5,saleable_gross_kg=40000 if index==0 else 800000+index*20000,expected_version=None)
        vid=saved[0]['voyage_id'];voyage_ids.append(vid)
        if index!=23:
            call(conn,'usp_TransitionVoyage',actor_id=admin,voyage_id=vid,target_status='OPEN',expected_version=rv(conn,'Voyage','voyage_id',vid))
    base=draft(conn,accounts['sales'],customers[0],voyage_ids[0],[dict(container_type_id=1,quantity=2,total_gross_kg=6000),dict(container_type_id=2,quantity=1,total_gross_kg=6000)],'并发演示基线：4 TEU / 12,000 kg')
    action(conn,accounts['sales'],base,'submit');action(conn,accounts['reviewer'],base,'confirm')
    for user,kg in [('sales',12000),('sales2',10000)]:
        bid=draft(conn,accounts[user],customers[1],voyage_ids[0],[dict(container_type_id=3,quantity=2,total_gross_kg=kg)],'并发待审样例，每单 4 TEU，最多成功一单')
        action(conn,accounts[user],bid,'submit')
    for index in range(80):
        user=accounts['sales' if index%2==0 else 'sales2'];vid=voyage_ids[1+index%22]
        bid=draft(conn,user,customers[index%20],vid,[dict(container_type_id=1+index%3,quantity=1+index%3,total_gross_kg=3000+index*100)],'教学样例：用于查询、统计与状态演示')
        state=index%5
        if state!=0:
            action(conn,user,bid,'submit')
            if state in [1,4]:action(conn,accounts['reviewer'],bid,'confirm')
            elif state==2:action(conn,accounts['reviewer'],bid,'reject','请核对货物申报信息后重新提交。')
            if state==4:action(conn,user,bid,'cancel','客户调整出运计划。')
    return accounts

def deploy(server,database,config_path=None,with_seed=True):
    if not re.fullmatch(r'HarborBooking(?:_[A-Za-z0-9]+)*',database):
        raise ValueError('专用数据库名称须为 HarborBooking 或其下划线后缀，禁止使用其他库名。')
    config_path=config_path or (ROOT/'.env' if database=='HarborBooking' else ROOT/f'.env.{database}.local')
    if config_path.exists():raise RuntimeError(f'配置文件已存在，拒绝覆盖：{config_path.name}')
    scripts=[ROOT/'sql'/name for name in ['01_schema.sql','02_views_triggers.sql','03_procedures.sql']]
    for script in scripts:
        if not script.exists():raise RuntimeError(f'缺少SQL脚本：{script.name}')
    with connect(server) as master:
        if master.execute('SELECT DB_ID(?)',database).fetchone()[0] is not None:
            raise RuntimeError(f'{database} 已存在。为保护数据，初始化已停止；使用现有 .env 启动，或指定一个新的专用库名。')
        if master.execute("SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int)").fetchone()[0]:
            raise RuntimeError('实例未启用 SQL 登录。请选择支持混合认证的实例；本程序不会自行修改服务器认证模式。')
        master.execute(f'CREATE DATABASE [{database}]')
    with connect(server,database) as conn:
        conn.timeout=60
        for script in scripts:
            for batch in re.split(r'^\s*GO\s*(?:--[^\n]*)?$',script.read_text(encoding='utf-8-sig'),flags=re.M|re.I):
                if batch.strip():rows(conn.cursor().execute(batch))
            print('已部署',script.name,flush=True)
        if with_seed:seed(conn)
    return configure_runtime(server,database,config_path)

def configure_runtime(server,database,config_path):
    """Provision a fresh restricted login after a successful deployment."""
    if not re.fullmatch(r'HarborBooking(?:_[A-Za-z0-9]+)*',database):
        raise ValueError('只允许配置本项目专用数据库。')
    if config_path.exists():raise RuntimeError('运行配置已存在，拒绝覆盖。')
    login=database+'_app';password=secrets.token_urlsafe(36)
    # Login name is validated above; generated password contains no quotes/semicolons.
    with connect(server) as master:
        if master.execute('SELECT SUSER_ID(?)',login).fetchone()[0] is not None:
            raise RuntimeError('同名运行账号已存在，未修改其密码。请选择新的专用数据库名。')
        master.execute(f"CREATE LOGIN [{login}] WITH PASSWORD=N'{password}',CHECK_POLICY=ON,DEFAULT_DATABASE=[{database}]")
    with connect(server,database) as conn:
        conn.execute(f'CREATE USER [{login}] FOR LOGIN [{login}]')
        for row in conn.execute("SELECT name FROM sys.views WHERE schema_id=SCHEMA_ID('dbo')").fetchall():
            conn.execute(f'GRANT SELECT ON OBJECT::dbo.[{row[0]}] TO [{login}]')
        for proc in ['usp_SaveBookingDraft','usp_BookingAction','usp_SaveVoyage','usp_TransitionVoyage','usp_MasterData','usp_SaveUser','usp_AuthenticateLookup']:
            conn.execute(f'GRANT EXECUTE ON OBJECT::dbo.[{proc}] TO [{login}]')
    connection_string=f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={brace(server)};DATABASE={brace(database)};UID={login};PWD={password};Encrypt=yes;TrustServerCertificate=yes'
    if config_path.exists():raise RuntimeError(f'配置文件已存在，拒绝覆盖：{config_path.name}')
    config_path.write_text(f"SECRET_KEY={secrets.token_urlsafe(48)}\nDB_CONNECTION_STRING='{connection_string}'\nPORT=5000\nHTTPS_ONLY=0\n",encoding='utf-8')
    print(f'数据库 {database} 初始化完成，运行账号仅有指定视图查询及过程执行权限。')
    print(f'配置已保存在 {config_path.name}；未输出数据库口令。')
    return connection_string

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',default='localhost');parser.add_argument('--database',default='HarborBooking')
    parser.add_argument('--no-seed',action='store_true')
    args=parser.parse_args()
    try:deploy(args.server,args.database,with_seed=not args.no_seed)
    except Exception as exc:
        print('初始化未完成：',exc,file=sys.stderr)
        print('已有数据库未被删除。请检查实例/权限及上方错误；不要对已有业务库执行清空操作。',file=sys.stderr)
        sys.exit(1)
