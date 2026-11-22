import openpyxl, pandas as pd, re, datetime as dt
from pathlib import Path
PT = {'jan':1,'fev':2,'mar':3,'abr':4,'mai':5,'jun':6,'jul':7,'ago':8,'set':9,'out':10,'nov':11,'dez':12}
def parse_month(x):
    if isinstance(x, (dt.datetime, dt.date)): return pd.Timestamp(x).to_period('M').to_timestamp()
    m = re.match(r'([a-zç]{3})/(\d{4})', str(x).strip().lower())
    return pd.Timestamp(int(m.group(2)), PT[m.group(1)], 1) if m else None

def parse_file(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ann, mon, audit = [], [], []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        send = None
        for r in rows[:15]:
            if r and r[0] == 'Mês de envio:':
                send = pd.Timestamp(r[1]).to_period('M').to_timestamp(); break
        if send is None: continue
        mt = re.match(r'([A-Za-z]{3})(\d{4})$', ws.title.strip())
        cell_send = send
        if mt:
            send = pd.Timestamp(int(mt.group(2)), PT[mt.group(1).lower()], 1)   # nome da aba manda
        i_ann = next((i for i,r in enumerate(rows) if r and r[0]=='Previsões Anuais'), None)
        i_mon = next((i for i,r in enumerate(rows) if r and r[0]=='Previsões Mensais'), None)
        def block(i0, i1, parse_hdr, store):
            hdr = rows[i0+1]
            cols = [(j, parse_hdr(hdr[j])) for j in range(2, len(hdr)) if hdr[j] is not None]
            var = None
            for r in rows[i0+2:i1]:
                if r[0] is not None: var = str(r[0]).strip()
                if var is None or r[1] is None: continue
                for j, key in cols:
                    v = r[j] if j < len(r) else None
                    if v is not None and key is not None:
                        store.append((send, var, str(r[1]).strip(), key, float(v)))
        if i_ann is not None:
            block(i_ann, i_mon if i_mon else len(rows), lambda x: int(float(x)), ann)
        if i_mon is not None:
            block(i_mon, len(rows), parse_month, mon)
        audit.append((ws.title, send.date(), cell_send.date(), send != cell_send, i_ann is not None, i_mon is not None))
    A = pd.DataFrame(ann, columns=['send_month','variable','stat','target_year','value'])
    M = pd.DataFrame(mon, columns=['send_month','variable','stat','target_month','value'])
    return A, M, pd.DataFrame(audit, columns=['sheet','send_month','cell_send_month','mismatch','has_annual','has_monthly'])

A, M, aud = parse_file('prisma/Estatisticas-das-previsoes-consolidadas.xlsx')
A.to_csv('out/prisma_annual_long.csv', index=False); M.to_csv('out/prisma_monthly_long.csv', index=False); aud.to_csv('out/prisma_sheet_audit.csv', index=False)
print(len(aud), aud.send_month.min(), aud.send_month.max(), 'dups:', aud.send_month.duplicated().sum())
print(A.variable.unique()); print(A.stat.unique())
print(A.groupby('variable').send_month.agg(['min','max','nunique']))
print(M.groupby('variable').send_month.agg(['min','max','nunique']))
# consistency with 2015-2020 file
A2, M2, aud2 = parse_file('prisma/01_disponibilizacao-das-previsoes-2015-2020.xlsx')
k = ['send_month','variable','stat','target_year']
mm = A.merge(A2, on=k, suffixes=('','_old'))
print('overlap rows', len(mm), 'max abs diff', (mm.value-mm.value_old).abs().max(), 'n diff>1e-6', ((mm.value-mm.value_old).abs()>1e-6).sum())
