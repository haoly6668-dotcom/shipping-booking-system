import json
import secrets
import threading
import time
from functools import wraps
from urllib.parse import urlsplit
from flask import Blueprint, request, session, g, redirect, render_template, flash, abort, Response, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import HTTPException
from .db import repo, BusinessError
from .services import BookingService, VoyageService, ReportService, integer, version, text_value, date_range, now

bp=Blueprint('web',__name__)
booking_service=BookingService();voyage_service=VoyageService();report_service=ReportService()
login_attempts={};attempt_lock=threading.Lock()
STATES={'DRAFT':'草稿','OPEN':'开放订舱','CLOSED':'已关闭','DEPARTED':'已离港','COMPLETED':'已完成',
        'SUBMITTED':'待审核','CONFIRMED':'已确认','REJECTED':'已驳回','CANCELLED':'已取消'}
MASTER={'customers':('Customer','v_Customers','customer_id','customer_name',{'customer_code':20,'customer_name':100,'contact_name':50,'contact_phone':30,'email':254}),
        'ports':('Port','v_Ports','port_id','port_name',{'port_code':10,'port_name':100,'country_region':60}),
        'vessels':('Vessel','v_Vessels','vessel_id','vessel_name',{'vessel_code':20,'vessel_name':100})}

def csrf_token():
    if '_csrf' not in session:session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']

def has_role(*roles):
    return bool(getattr(g,'user',None) and set(roles)&set(g.user['roles']))

def require(*roles):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if not g.user:return redirect('/login?next='+request.path)
            if roles and not has_role(*roles):abort(403)
            return fn(*args,**kwargs)
        return wrapped
    return decorate

def load_user(user_id):
    user=repo.one('SELECT * FROM dbo.v_Users WHERE user_id=? AND is_active=1',(user_id,))
    if user:user['roles']=[r['role_code'] for r in repo.query('SELECT role_code FROM dbo.v_UserRoles WHERE user_id=?',(user_id,))]
    return user

def install_helpers(app):
    @app.before_request
    def prepare():
        g.user=None
        if request.endpoint=='static':return
        if session.get('user_id'):
            g.user=load_user(session['user_id'])
            if not g.user:session.clear()
        if request.method=='POST':
            token=request.form.get('csrf_token') or request.headers.get('X-CSRF-Token','')
            if not secrets.compare_digest(str(session.get('_csrf','')),str(token)) or not token:
                current_app.logger.warning('CSRF failure path=%s',request.path)
                raise BusinessError('表单已过期或验证失败，请刷新页面重试。',400)

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.endpoint!='static':response.headers['Cache-Control']='no-store'
        return response

    @app.context_processor
    def globals_for_templates():
        return dict(current_user=getattr(g,'user',None),has_role=has_role,csrf_token=csrf_token)
    app.jinja_env.filters['status_label']=lambda value:STATES.get(value,value or '—')
    app.jinja_env.filters['status_class']=lambda value:str(value or '').lower()
    app.jinja_env.filters['num']=lambda value,decimals=0:format(value or 0,','+'.'+str(decimals)+'f')
    app.jinja_env.filters['datetime']=lambda value:value.strftime('%Y-%m-%d %H:%M') if hasattr(value,'strftime') else (str(value).replace('T',' ')[:16] if value else '—')

    @app.errorhandler(BusinessError)
    def business_error(exc):
        current_app.logger.warning('Rejected operation user=%s path=%s reason=%s',session.get('user_id'),request.path,exc.message)
        return render_template('error.html',code=exc.status,message=exc.message),exc.status
    @app.errorhandler(HTTPException)
    def http_error(exc):
        messages={403:'没有执行此操作或查看该数据的权限。',404:'没有找到这个页面或记录。',405:'该地址不支持此操作。',413:'提交的数据过大。'}
        return render_template('error.html',code=exc.code,message=messages.get(exc.code,'请求无法处理。')),exc.code
    @app.errorhandler(Exception)
    def unexpected(exc):
        current_app.logger.exception('Unhandled application error')
        if app.testing:raise exc
        return render_template('error.html',code=500,message='发生了意外错误，请稍后重试。'),500

@bp.route('/health')
def health():
    repo.scalar('SELECT 1 AS ok')
    return {'status':'ok'}

@bp.route('/login',methods=['GET','POST'])
def login():
    if g.user:return redirect('/')
    error=None
    if request.method=='POST':
        username=request.form.get('username','').strip()[:50];password=request.form.get('password','')
        key=(request.remote_addr,username.lower());clock=time.monotonic()
        with attempt_lock:
            for k in list(login_attempts):
                if clock-login_attempts[k][1]>300:login_attempts.pop(k,None)
            record=login_attempts.get(key,(0,clock))
        if record[0]>=10:
            return render_template('login.html',error='尝试次数过多，请五分钟后再试。',form=request.form),429
        rows=repo.procedure('usp_AuthenticateLookup',username=username)
        found=rows[0] if rows else None
        valid=bool(found and found['is_active'] and len(password)<=128 and check_password_hash(found['password_hash'],password))
        if valid:
            with attempt_lock:login_attempts.pop(key,None)
            session.clear();session['user_id']=found['user_id'];session.permanent=True;csrf_token()
            target=request.form.get('next') or request.args.get('next','/')
            # Redirect only to a local path; reject scheme-relative URLs and backslashes.
            if not target.startswith('/') or target.startswith('//') or '\\' in target or urlsplit(target).netloc:target='/'
            return redirect(target)
        with attempt_lock:
            if len(login_attempts)<1000 or key in login_attempts:login_attempts[key]=(record[0]+1,record[1])
        current_app.logger.warning('Login rejected username=%r',username)
        error='用户名或密码不正确，或账户已停用。'
    return render_template('login.html',error=error,form=request.form),401 if error else 200

@bp.post('/logout')
def logout():
    session.clear();return redirect('/login')

def booking_scope():
    return ('1=1',[]) if has_role('REVIEWER') else ('created_by=?',[g.user['user_id']])

def get_booking(booking_id):
    row=repo.one('SELECT * FROM dbo.v_Bookings WHERE booking_id=?',(booking_id,))
    if not row:abort(404)
    if not has_role('REVIEWER') and (not has_role('SALES') or row['created_by']!=g.user['user_id']):abort(403)
    return row

def paged(view,where,params,order,page_size=20):
    raw=request.args.get('page','1')
    page=integer(raw,'页码',maximum=100000)
    total=int(repo.scalar('SELECT COUNT_BIG(*) FROM dbo.'+view+' WHERE '+where,params))
    pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    rows=repo.query('SELECT * FROM dbo.'+view+' WHERE '+where+' ORDER BY '+order+' OFFSET ? ROWS FETCH NEXT ? ROWS ONLY',[*params,(page-1)*page_size,page_size])
    from urllib.parse import urlencode
    args=request.args.to_dict()
    def link(p):return request.path+'?'+urlencode(dict(args,page=p))
    return rows,dict(page=page,pages=pages,total=total,prev_url=link(page-1) if page>1 else None,next_url=link(page+1) if page<pages else None)

@bp.get('/')
@require()
def dashboard():
    clock=now()
    stats={'open_voyages':repo.scalar("SELECT COUNT(*) FROM dbo.v_VoyageCapacity WHERE status='OPEN' AND booking_cutoff_at>?",[clock]),'pending_bookings':0,'confirmed_teu':0,'my_bookings':0}
    recent=[]
    pending=[]
    analysis_summary=None
    if has_role('SALES','REVIEWER'):
        scope,params=booking_scope()
        recent=repo.query('SELECT TOP (5) * FROM dbo.v_Bookings WHERE '+scope+' ORDER BY booking_id DESC',params)
        stats['pending_bookings']=repo.scalar("SELECT COUNT(*) FROM dbo.v_Bookings WHERE status='SUBMITTED' AND "+scope,params)
        stats['confirmed_teu']=repo.scalar("SELECT COALESCE(SUM(total_teu),0) FROM dbo.v_Bookings WHERE status='CONFIRMED' AND "+scope,params)
        stats['my_bookings']=repo.scalar('SELECT COUNT(*) FROM dbo.v_Bookings WHERE created_by=?',[g.user['user_id']])
        if has_role('REVIEWER'):
            pending=repo.query("SELECT TOP (5) * FROM dbo.v_Bookings WHERE status='SUBMITTED' AND created_by<>? ORDER BY booking_id",[g.user['user_id']])
            stats['reviewable']=repo.scalar("SELECT COUNT(*) FROM dbo.v_Bookings WHERE status='SUBMITTED' AND created_by<>?",[g.user['user_id']])
    if has_role('ANALYST'):
        analysis_summary=repo.one("SELECT COUNT_BIG(*) confirmed_bookings, COALESCE(SUM(total_teu),0) total_teu, COALESCE(SUM(total_gross_kg),0) total_gross_kg FROM dbo.v_Bookings WHERE status='CONFIRMED'")
    stats['departing_soon']=repo.scalar("SELECT COUNT(*) FROM dbo.v_VoyageCapacity WHERE status IN ('OPEN','CLOSED') AND departure_at>? AND departure_at<=DATEADD(day,7,?)",[clock,clock])
    next_cutoff=repo.scalar("SELECT MIN(booking_cutoff_at) FROM dbo.v_VoyageCapacity WHERE status='OPEN' AND booking_cutoff_at>?",[clock])
    upcoming=repo.query("SELECT TOP (5) * FROM dbo.v_VoyageCapacity WHERE status='OPEN' AND booking_cutoff_at>? ORDER BY departure_at",[clock])
    for row in upcoming:row['can_book']=has_role('SALES')
    return render_template('dashboard.html',stats=stats,recent_bookings=recent,pending_bookings=pending,analysis_summary=analysis_summary,next_cutoff=next_cutoff,upcoming_voyages=upcoming,today_label=clock.strftime('%Y年%m月%d日'))

@bp.get('/voyages')
@require()
def voyages():
    conditions=['1=1'];params=[]
    for name in ['origin_port_id','destination_port_id']:
        if request.args.get(name):conditions.append(name+'=?');params.append(integer(request.args[name]))
    if request.args.get('q'):
        conditions.append('(voyage_no LIKE ? OR vessel_name LIKE ?)');params.extend(['%'+request.args['q'][:100]+'%']*2)
    if request.args.get('status'):
        conditions.append('status=?');params.append(request.args['status'][:12])
    start,end=date_range(request.args)
    for op,d in [('>=',start),('<',end)]:
        if d:conditions.append('departure_at '+op+' ?');params.append(d)
    for arg,col in [('min_teu','remaining_teu'),('min_gross_kg','remaining_gross_kg')]:
        if request.args.get(arg):conditions.append(col+'>=?');params.append(integer(request.args[arg],arg,maximum=99999999999))
    rows,pagination=paged('v_VoyageCapacity',' AND '.join(conditions),params,'departure_at DESC,voyage_id DESC')
    for row in rows:row['can_book']=has_role('SALES') and row['status']=='OPEN' and row['booking_cutoff_at']>now()
    return render_template('voyages.html',voyages=rows,ports=repo.query('SELECT * FROM dbo.v_Ports ORDER BY port_name'),pagination=pagination)

@bp.route('/voyages/new',methods=['GET','POST'])
@bp.route('/voyages/<int:voyage_id>/edit',methods=['GET','POST'])
@require('ADMIN')
def voyage_form(voyage_id=None):
    voyage=repo.one('SELECT * FROM dbo.v_VoyageCapacity WHERE voyage_id=?',[voyage_id]) if voyage_id else None
    if voyage_id and not voyage:abort(404)
    errors=[];status=200
    if request.method=='POST':
        try:
            voyage_service.save(g.user['user_id'],request.form,voyage_id);flash('航次已保存。','success');return redirect('/voyages')
        except BusinessError as exc:errors=[exc.message];status=exc.status
    return render_template('voyage_form.html',voyage=voyage,form=request.form if request.method=='POST' else (voyage or {}),errors=errors,
        ports=repo.query('SELECT * FROM dbo.v_Ports ORDER BY port_name'),vessels=repo.query('SELECT * FROM dbo.v_Vessels ORDER BY vessel_name')),status

@bp.post('/voyages/<int:voyage_id>/transition')
@require('ADMIN')
def voyage_transition(voyage_id):
    target=request.form.get('target_status','')
    if target not in {'OPEN','CLOSED','DEPARTED','COMPLETED'}:raise BusinessError('未知航次状态。',400)
    repo.procedure('usp_TransitionVoyage',actor_id=g.user['user_id'],voyage_id=voyage_id,target_status=target,expected_version=version(request.form.get('expected_version'),True))
    flash('航次状态已更新。','success');return redirect('/voyages')

@bp.get('/bookings')
@require('SALES','REVIEWER')
def bookings():
    scope,params=booking_scope();conditions=[scope]
    if request.args.get('q'):
        conditions.append('(booking_no LIKE ? OR customer_name LIKE ? OR voyage_no LIKE ?)');params.extend(['%'+request.args['q'][:100]+'%']*3)
    if request.args.get('status'):conditions.append('status=?');params.append(request.args['status'][:12])
    rows,pagination=paged('v_Bookings',' AND '.join(conditions),params,'booking_id DESC')
    return render_template('bookings.html',bookings=rows,pagination=pagination)

@bp.route('/bookings/new',methods=['GET','POST'])
@bp.route('/bookings/<int:booking_id>/edit',methods=['GET','POST'])
@require('SALES')
def booking_form(booking_id=None):
    booking=get_booking(booking_id) if booking_id else None
    if booking and booking['created_by']!=g.user['user_id']:abort(403)
    if booking and booking['status']!='DRAFT':raise BusinessError('仅草稿订舱可以编辑。')
    items=repo.query('SELECT * FROM dbo.v_BookingItems WHERE booking_id=? ORDER BY container_type_id',[booking_id]) if booking else []
    errors=[];status=200
    form=request.form if request.method=='POST' else dict(booking or {},voyage_id=booking['voyage_id'] if booking else request.args.get('voyage_id',''))
    if request.method=='POST':
        try:
            saved=booking_service.save(g.user['user_id'],request.form,booking_id);flash('订舱草稿已保存。','success');return redirect('/bookings/'+str(saved['booking_id']))
        except BusinessError as exc:
            errors=[exc.message];status=exc.status
            items=[dict(zip(('container_type_id','quantity','total_gross_kg'),values)) for values in zip(*[request.form.getlist(k) for k in ('container_type_id','quantity','total_gross_kg')])]
    available=repo.query("SELECT * FROM dbo.v_VoyageCapacity WHERE (status='OPEN' AND booking_cutoff_at>?) OR voyage_id=? ORDER BY departure_at",[now(),booking['voyage_id'] if booking else -1])
    return render_template('booking_form.html',booking=booking,items=items,form=form,errors=errors,customers=repo.query('SELECT * FROM dbo.v_Customers ORDER BY customer_name'),voyages=available,container_types=repo.query('SELECT * FROM dbo.v_ContainerTypes ORDER BY container_type_id')),status

@bp.get('/bookings/<int:booking_id>')
@require('SALES','REVIEWER')
def booking_detail(booking_id):
    booking=get_booking(booking_id);actions=[]
    capacity=repo.one('SELECT * FROM dbo.v_VoyageCapacity WHERE voyage_id=?',[booking['voyage_id']])
    owner=has_role('SALES') and booking['created_by']==g.user['user_id']
    if owner:
        if booking['status']=='DRAFT':actions+=['edit','submit']
        if booking['status']=='SUBMITTED':actions+=['withdraw']
        if booking['status']=='REJECTED':actions+=['reopen']
        if booking['status']!='CANCELLED' and (booking['status']!='CONFIRMED' or booking['voyage_status'] not in ['DEPARTED','COMPLETED']):actions+=['cancel']
    if has_role('REVIEWER') and booking['created_by']!=g.user['user_id'] and booking['status']=='SUBMITTED':
        actions+=['reject']
        if capacity['status']=='OPEN' and capacity['booking_cutoff_at']>now():actions+=['confirm']
    if capacity['status']!='OPEN' or capacity['booking_cutoff_at']<=now():actions=[a for a in actions if a!='submit']
    history=repo.query('SELECT * FROM dbo.v_BookingHistory WHERE booking_id=? ORDER BY history_id',[booking_id])
    for row in history:row['changed_by_name']=row.get('display_name')
    return render_template('booking_detail.html',booking=booking,items=repo.query('SELECT * FROM dbo.v_BookingItems WHERE booking_id=? ORDER BY container_type_id',[booking_id]),history=history,allowed_actions=actions,capacity=capacity)

@bp.post('/bookings/<int:booking_id>/action')
@require('SALES','REVIEWER')
def booking_action(booking_id):
    booking=get_booking(booking_id);action=request.form.get('action')
    if action in ['confirm','reject']:
        if not has_role('REVIEWER') or booking['created_by']==g.user['user_id']:abort(403)
    elif not has_role('SALES') or booking['created_by']!=g.user['user_id']:abort(403)
    booking_service.action(g.user['user_id'],booking_id,request.form)
    flash('订舱操作成功。','success');return redirect('/bookings/'+str(booking_id))

@bp.route('/masters/<entity>',methods=['GET','POST'])
@require('ADMIN')
def masters(entity):
    if entity not in MASTER:abort(404)
    table,view,idkey,namekey,fields=MASTER[entity];errors=[];status=200;editing=None
    selected=request.form.get('id') if request.method=='POST' else request.args.get('edit')
    if selected:
        editing=repo.one('SELECT * FROM dbo.'+view+' WHERE '+idkey+'=?',[integer(selected)])
        if not editing:abort(404)
    if request.method=='POST':
        try:
            action=request.form.get('action','save')
            if action not in ['save','delete']:raise BusinessError('未知资料操作。',400)
            data=None
            if action=='save':
                data={k:text_value(request.form,k,size,k!='email') for k,size in fields.items()}
                data['is_active']=request.form.get('is_active','1')=='1'
                if entity=='vessels':data['nominal_teu']=integer(request.form.get('nominal_teu'),'标称 TEU')
                if data.get('email') and ('@' not in data['email'] or ' ' in data['email']):raise BusinessError('邮箱格式不正确。',400)
            repo.procedure('usp_MasterData',actor_id=g.user['user_id'],entity=table,action=action,id=integer(selected,optional=True),data_json=json.dumps(data,ensure_ascii=False) if data is not None else None,expected_version=version(request.form.get('expected_version'),bool(selected)))
            flash('资料已保存。' if action=='save' else '未被引用的资料已删除。','success');return redirect('/masters/'+entity)
        except BusinessError as exc:errors=[exc.message];status=exc.status
    q=request.args.get('q','')[:100]
    rows,pagination=paged(view,namekey+' LIKE ?',['%'+q+'%'],idkey+' DESC')
    return render_template('masters.html',entity=entity,records=rows,editing=editing,form=request.form if request.method=='POST' else (editing or {}),errors=errors,pagination=pagination),status

@bp.route('/users',methods=['GET','POST'])
@require('ADMIN')
def users():
    records=repo.query('SELECT * FROM dbo.v_Users ORDER BY user_id')
    memberships=repo.query('SELECT * FROM dbo.v_UserRoles')
    for row in records:row['roles']=[r['role_code'] for r in memberships if r['user_id']==row['user_id']]
    selected=request.form.get('user_id') if request.method=='POST' else request.args.get('edit')
    editing=next((r for r in records if str(r['user_id'])==str(selected)),None)
    if selected and not editing:abort(404)
    errors=[];status=200
    if request.method=='POST':
        try:
            password=request.form.get('password','')
            if password and (len(password)<10 or len(password)>128):raise BusinessError('密码长度须为 10 至 128 个字符。',400)
            if not editing and not password:raise BusinessError('新用户必须设置密码。',400)
            repo.procedure('usp_SaveUser',actor_id=g.user['user_id'],user_id=integer(selected,optional=True),username=text_value(request.form,'username',50),display_name=text_value(request.form,'display_name',50),password_hash=generate_password_hash(password) if password else None,is_active=request.form.get('is_active')=='1',roles_json=json.dumps(request.form.getlist('roles')),expected_version=version(request.form.get('expected_version'),bool(selected)))
            flash('用户与角色已更新。','success');return redirect('/users')
        except BusinessError as exc:errors=[exc.message];status=exc.status
    return render_template('users.html',users=records,roles=repo.query('SELECT * FROM dbo.v_Roles'),editing=editing,form=request.form if request.method=='POST' else (editing or {}),errors=errors),status

@bp.get('/reports')
@require('ANALYST')
def reports():return render_template('reports.html',**report_service.data(request.args))

@bp.get('/reports/export')
@require('ANALYST')
def export():
    kind=request.args.get('kind','customer')
    schemas={
      'monthly':('monthly_stats',[('month','计划离港月份'),('booking_count','确认订舱数'),('total_teu','确认订舱TEU'),('total_gross_kg','申报总毛重kg')]),
      'customer':('customer_stats',[('customer_name','客户名称'),('booking_count','确认订舱数'),('total_teu','确认订舱TEU'),('total_gross_kg','申报总毛重kg')]),
      'route':('route_stats',[('origin_port_name','起运港'),('destination_port_name','目的港'),('voyage_count','航次数'),('used_teu','确认订舱TEU'),('saleable_teu','可售TEU'),('utilization_pct','TEU利用率百分比')])}
    if kind not in schemas:raise BusinessError('未知报表种类。',400)
    key,fields=schemas[kind];data=report_service.data(request.args)
    return Response(report_service.csv(data[key],fields),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="harbor-{kind}.csv"'})

@bp.get('/audit')
@require('ADMIN')
def audit():
    conditions=['1=1'];params=[]
    if request.args.get('q'):
        conditions.append('(entity_name LIKE ? OR entity_key LIKE ? OR display_name LIKE ?)');params.extend(['%'+request.args['q'][:100]+'%']*3)
    if request.args.get('action'):conditions.append('action_code=?');params.append(request.args['action'][:30])
    start,end=date_range(request.args)
    for op,d in [('>=',start),('<',end)]:
        if d:conditions.append('occurred_at '+op+' ?');params.append(d)
    rows,pagination=paged('v_Audit',' AND '.join(conditions),params,'audit_id DESC')
    for row in rows:row['actor_name']=row.get('display_name')
    return render_template('audit.html',logs=rows,pagination=pagination)
