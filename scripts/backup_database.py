"""Make a new copy-only backup and optionally restore to a new verification database."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from setup_database import connect, rows, ROOT

def backup(server,database,verify_restore=False):
    if not re.fullmatch(r'HarborBooking(?:_[A-Za-z0-9]+)*',database):
        raise ValueError('只允许备份本项目的专用数据库。')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    dest=ROOT/'backups';dest.mkdir(exist_ok=True)
    with connect(server) as conn:
        if not conn.execute('SELECT DB_ID(?)',database).fetchone()[0]:raise ValueError('数据库不存在。')
        directories=conn.execute("SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(260)), CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260)),CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS nvarchar(260))").fetchone()
        source=dest/f'{database}_{stamp}.bak'
        if source.exists():raise RuntimeError('备份目标已存在，拒绝覆盖。')
        conn.timeout=180
        rows(conn.cursor().execute(f'BACKUP DATABASE [{database}] TO DISK=? WITH COPY_ONLY,CHECKSUM',str(source)))
        rows(conn.cursor().execute('RESTORE VERIFYONLY FROM DISK=? WITH CHECKSUM',str(source)))
        output=source
        report={'database':database,'backup_file':str(output),'verifyonly':'passed','restored_database':None}
        if verify_restore:
            name=f'HarborBooking_RestoreCheck_{stamp}'
            if conn.execute('SELECT DB_ID(?)',name).fetchone()[0]:raise RuntimeError('验证库已存在，拒绝覆盖。')
            files=rows(conn.cursor().execute('RESTORE FILELISTONLY FROM DISK=?',str(source)))
            clauses=[];params=[str(source)]
            for index,item in enumerate(files):
                is_log=item['Type']=='L';suffix='.ldf' if is_log else ('.mdf' if index==0 else '.ndf')
                path=Path(directories[2] if is_log else directories[1])/f'{name}_{index}{suffix}'
                if path.exists():raise RuntimeError('验证数据文件已存在，拒绝覆盖。')
                clauses.append('MOVE ? TO ?');params.extend([item['LogicalName'],str(path)])
            rows(conn.cursor().execute(f'RESTORE DATABASE [{name}] FROM DISK=? WITH '+','.join(clauses)+', RECOVERY',params))
            report['restored_database']=name
            for table in ['Customer','Port','Vessel','Voyage','Booking','BookingItem','BookingStatusHistory','AuditLog']:
                original=conn.execute(f'SELECT COUNT_BIG(*) FROM [{database}].dbo.[{table}]').fetchone()[0]
                restored=conn.execute(f'SELECT COUNT_BIG(*) FROM [{name}].dbo.[{table}]').fetchone()[0]
                if original!=restored:raise RuntimeError('恢复后的行数与原库不一致。')
            original=conn.execute(f'SELECT SUM(used_teu),SUM(used_gross_kg) FROM [{database}].dbo.v_VoyageCapacity').fetchone()
            restored=conn.execute(f'SELECT SUM(used_teu),SUM(used_gross_kg) FROM [{name}].dbo.v_VoyageCapacity').fetchone()
            if tuple(original)!=tuple(restored):raise RuntimeError('恢复后的容量汇总不一致。')
            report['row_counts_and_capacity']='passed'
        (ROOT/'docs'/'backup-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',default='localhost');parser.add_argument('--database',default='HarborBooking')
    parser.add_argument('--verify-restore',action='store_true')
    args=parser.parse_args();backup(args.server,args.database,args.verify_restore)
