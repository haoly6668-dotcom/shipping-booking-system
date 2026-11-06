"""HTTP integration tests against the separate seeded SQL Server test database."""
import re
from pathlib import Path
from html.parser import HTMLParser
import pytest
import pyodbc
from dotenv import dotenv_values
from app import create_app

ROOT=Path(__file__).resolve().parents[1]

class Inputs(HTMLParser):
    def __init__(self):super().__init__();self.fields={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('name'):
            self.fields[attrs['name']]=attrs.get('value','')

def token(client,path='/login'):
    response=client.get(path);parser=Inputs();parser.feed(response.get_data(as_text=True))
    assert response.status_code==200, response.get_data(as_text=True)[:500]
    return parser.fields['csrf_token']

def login(client,user='sales'):
    result=client.post('/login',data=dict(username=user,password='Harbor@2026',csrf_token=token(client)))
    assert result.status_code==302
    return client

@pytest.fixture(scope='module')
def web_app():
    config=dotenv_values(ROOT/'.env.HarborBooking_Test.local')
    connection_string=config.get('DB_CONNECTION_STRING')
    if not connection_string:pytest.fail('请先用 setup_database.py 初始化 HarborBooking_Test 及其配置。')
    with pyodbc.connect(connection_string,autocommit=True) as connection:
        assert connection.execute('SELECT DB_NAME()').fetchone()[0].endswith('_Test')
    return create_app({'TESTING':True,'SECRET_KEY':'test-only-random-fixture-key','DB_CONNECTION_STRING':connection_string})

@pytest.fixture
def client(web_app):return web_app.test_client()

def dbone(app,sql,*params):
    with pyodbc.connect(app.config['DB_CONNECTION_STRING'],autocommit=True) as conn:
        cursor=conn.execute(sql,*params);row=cursor.fetchone()
        return dict(zip([item[0] for item in cursor.description],row)) if row else None

def ver(app,bid):
    return dbone(app,'SELECT CONVERT(varchar(18),CONVERT(binary(8),row_version),1) version FROM dbo.v_Bookings WHERE booking_id=?',bid)['version']

@pytest.mark.parametrize('user,paths',[
    ('admin',['/','/voyages','/voyages/new','/masters/customers','/masters/ports','/masters/vessels','/users','/audit']),
    ('sales',['/','/voyages','/bookings','/bookings/new']),
    ('reviewer',['/','/voyages','/bookings']),
    ('analyst',['/','/reports','/reports?date_from=2026-01-01&date_to=2030-12-31'])])
def test_all_role_pages_render(client,user,paths):
    login(client,user)
    for path in paths:
        result=client.get(path)
        assert result.status_code==200,(path,result.get_data(as_text=True)[:500])

def test_authentication_csrf_and_open_redirect(client):
    assert client.get('/bookings').status_code==302
    csrf=token(client)
    assert client.post('/login',data={'username':'sales','password':'bad','csrf_token':csrf}).status_code==401
    assert client.post('/login',data={'username':'sales','password':'Harbor@2026'}).status_code==400
    result=client.post('/login',data={'username':'sales','password':'Harbor@2026','csrf_token':csrf,'next':'//evil.example'})
    assert result.status_code==302 and result.headers['Location']=='/'
    assert client.post('/logout').status_code==400

@pytest.mark.parametrize('user,path',[('sales','/users'),('sales','/reports'),('reviewer','/voyages/new'),('analyst','/bookings'),('admin','/bookings')])
def test_no_implicit_or_cross_role_access(client,user,path):
    login(client,user);assert client.get(path).status_code==403

def test_order_ownership(client,web_app):
    login(client,'sales')
    other=dbone(web_app,"SELECT TOP (1) b.booking_id FROM dbo.v_Bookings b JOIN dbo.v_Users u ON u.user_id=b.created_by WHERE u.username='sales2' ORDER BY b.booking_id")
    assert other
    assert client.get('/bookings/'+str(other['booking_id'])).status_code==403

def test_complete_booking_browser_flow(client,web_app):
    login(client,'sales')
    voyage=dbone(web_app,"SELECT TOP (1) voyage_id FROM dbo.v_VoyageCapacity WHERE status='OPEN' AND remaining_teu>20 AND booking_cutoff_at>DATEADD(hour,8,SYSUTCDATETIME()) ORDER BY voyage_id")
    customer=dbone(web_app,'SELECT TOP (1) customer_id FROM dbo.v_Customers WHERE is_active=1 ORDER BY customer_id')
    result=client.post('/bookings/new',data={'csrf_token':token(client,'/bookings/new'),'customer_id':customer['customer_id'],'voyage_id':voyage['voyage_id'],'cargo_description':'HTTP集成测试','remark':'测试独立订单','container_type_id':'1','quantity':'1','total_gross_kg':'1000.123'})
    assert result.status_code==302,result.get_data(as_text=True)
    path=result.headers['Location'];bid=int(path.rsplit('/',1)[-1])
    assert client.get(path).status_code==200
    result=client.post(path+'/action',data={'csrf_token':token(client,path),'action':'submit','expected_version':ver(web_app,bid)})
    assert result.status_code==302
    reviewer=login(web_app.test_client(),'reviewer')
    result=reviewer.post(path+'/action',data={'csrf_token':token(reviewer,path),'action':'confirm','expected_version':ver(web_app,bid)})
    assert result.status_code==302,result.get_data(as_text=True)
    assert dbone(web_app,'SELECT status FROM dbo.v_Bookings WHERE booking_id=?',bid)['status']=='CONFIRMED'
    result=client.post(path+'/action',data={'csrf_token':token(client,path),'action':'cancel','reason':'测试取消','expected_version':ver(web_app,bid)})
    assert result.status_code==302,result.get_data(as_text=True)
    assert dbone(web_app,'SELECT status FROM dbo.v_Bookings WHERE booking_id=?',bid)['status']=='CANCELLED'

def test_reports_export_and_invalid_filters(client):
    login(client,'analyst')
    for kind in ['monthly','customer','route']:
        result=client.get('/reports/export?kind='+kind)
        assert result.status_code==200
        assert result.data.startswith(b'\xef\xbb\xbf')
        assert 'attachment' in result.headers['Content-Disposition']
    assert client.get('/reports?date_from=bad').status_code==400
    assert client.get('/reports/export?kind=unknown').status_code==400
    assert client.get('/reports?date_from=2099-01-01&date_to=2099-12-31').status_code==200

def test_input_validation_is_visible_and_preserves_form(client):
    login(client,'sales')
    result=client.post('/bookings/new',data={'csrf_token':token(client,'/bookings/new'),'customer_id':'1','voyage_id':'1','cargo_description':'保留这段输入','container_type_id':'1','quantity':'0','total_gross_kg':'12'})
    assert result.status_code==400
    assert '保留这段输入' in result.get_data(as_text=True)

def test_search_parameterization_and_headers(client):
    login(client,'sales')
    result=client.get('/bookings',query_string={'q':"x' OR 1=1 --"})
    assert result.status_code==200
    assert result.headers['X-Content-Type-Options']=='nosniff'
    assert result.headers['Cache-Control']=='no-store'
