import pandas as pd, numpy as np, openpyxl
A = pd.read_csv('out/prisma_annual_long.csv', parse_dates=['send_month'])
M = pd.read_csv('out/prisma_monthly_long.csv', parse_dates=['send_month','target_month'])
# --- correcao: na aba Mai2025 os rotulos de Divida Bruta (GC) e Resultado Nominal estao trocados ---
_db, _nm = 'Dívida Bruta do Governo Central (% do PIB)', 'Resultado Nominal do Governo Central'
_m = A.send_month == pd.Timestamp('2025-05-01')
assert A[_m & (A.variable==_db)].value.abs().min() > 300 and A[_m & (A.variable==_nm)].value.abs().max() < 200
A.loc[_m & (A.variable==_db), 'variable'] = '__tmp'
A.loc[_m & (A.variable==_nm), 'variable'] = _db
A.loc[_m & (A.variable=='__tmp'), 'variable'] = _nm
pd.DataFrame([{'send_month':'2025-05-01','issue':'rotulos de Divida Bruta (GC) e Resultado Nominal trocados na aba Mai2025','fix':'rotulos trocados de volta (valores: DBGG ~80%, nominal ~-960000)'}]).to_csv('out/prisma_corrections_log.csv', index=False)
A.to_csv('out/prisma_annual_long_corrected.csv', index=False)

# --- realizado (serie-historica.xlsx) ---
wb = openpyxl.load_workbook('prisma/serie-historica.xlsx', read_only=True, data_only=True)
rows = list(wb.worksheets[0].iter_rows(values_only=True))
hdr = rows[4]
real = pd.DataFrame([r[1:9] for r in rows[5:] if r[1] is not None], columns=[str(h).strip() for h in hdr[1:9]])
real.columns = ['month','year','arrec','rec_liq','despesa','primario','nominal','dbgg']
real['month'] = pd.to_datetime(real['month'])
for c in ['arrec','rec_liq','despesa','primario','nominal','dbgg']:
    real[c] = pd.to_numeric(real[c], errors='coerce')
real.loc[real.arrec==0, ['arrec','dbgg']] = np.nan     # zeros = ausente
real.to_csv('out/prisma_realizado_mensal.csv', index=False)

# --- (1) surpresa mensal de primario: realizado(m) - mediana Prisma para m enviada em m ---
VP = 'Resultado Primário do Governo Central'
fc = M[(M.variable==VP)&(M.stat=='Mediana')&(M.send_month==M.target_month)][['target_month','value']]
fc = fc.rename(columns={'target_month':'month','value':'prisma_fc_primario_m'})
s = real[['month','primario']].merge(fc, on='month', how='inner')
s['prisma_surp_primario_brl_mi'] = s.primario - s.prisma_fc_primario_m
s = s.rename(columns={'primario':'realizado_primario'})
# prisma tem tb forecast de meses anteriores ao envio? checar cobertura
print('surpresas mensais:', len(s), s.month.min().date(), s.month.max().date())

# --- (2) revisoes anuais Prisma: mesma variavel e ano-alvo, entre envios consecutivos ---
def annual_rev(var, name):
    d = A[(A.variable==var)&(A.stat=='Mediana')].copy()
    d['h'] = d.target_year - d.send_month.dt.year
    d = d.sort_values(['target_year','send_month'])
    d['prev_send'] = d.groupby('target_year').send_month.shift(1)
    d['prev'] = d.groupby('target_year').value.shift(1)
    d = d[(d.send_month - d.prev_send).dt.days.between(25, 35)]   # so envios em meses consecutivos
    d['rev'] = d.value - d.prev
    p = d[d.h.between(0,3)].pivot_table(index='send_month', columns='h', values='rev')
    p.columns = [f'{name}_h{int(c)}' for c in p.columns]
    return p.rename_axis('month')
P = annual_rev(VP, 'prisma_rev_primario_brl_mi')
D1 = annual_rev('Dívida Bruta do Governo Central (% do PIB)', 'prisma_rev_dbgg_gc_pp')
D2 = annual_rev('Dívida Bruta do Governo Geral (em % do PIB)', 'prisma_rev_dbgg_gg_pp')

# --- (3) Focus: mediana (baseCalculo=0) no fim de cada mes por ano-alvo; variacao mensal ---
def focus_rev(file, name):
    f = pd.read_csv(file, parse_dates=['Data'])
    f = f[(f.baseCalculo==0)&(f.Data < '2026-11-01')].copy()   # exclui mes parcial (nov/2026 incompleto)
    f['month'] = f.Data.dt.to_period('M').dt.to_timestamp()
    last = f.sort_values('Data').groupby(['month','DataReferencia']).tail(1)
    last = last.sort_values(['DataReferencia','month'])
    last['prev_m'] = last.groupby('DataReferencia').month.shift(1)
    last['prev'] = last.groupby('DataReferencia').Mediana.shift(1)
    last = last[(last.month - last.prev_m).dt.days.between(25,35)]
    last['h'] = last.DataReferencia - last.month.dt.year
    last['rev'] = last.Mediana - last.prev
    p = last[last.h.between(0,3)].pivot_table(index='month', columns='h', values='rev')
    p.columns = [f'{name}_h{int(c)}' for c in p.columns]
    return p
F = [focus_rev('focus/focus_anuais_resultado_primário.csv','focus_rev_primario_pp'),
     focus_rev('focus/focus_anuais_dívida_líquida_do_setor_público.csv','focus_rev_dlsp_pp'),
     focus_rev('focus/focus_anuais_dívida_bruta_do_governo_geral.csv','focus_rev_dbgg_pp'),
     focus_rev('focus/focus_anuais_resultado_nominal.csv','focus_rev_nominal_pp')]

panel = s[['month','realizado_primario','prisma_fc_primario_m','prisma_surp_primario_brl_mi']].set_index('month')
panel = panel.join([P, D1, D2] + F, how='outer').sort_index()
panel['release_month_approx'] = panel.index + pd.offsets.MonthBegin(1)   # primario do mes m sai ~fim de m+1
panel.reset_index().to_csv('out/fiscal_news_monthly.csv', index=False)

# --- diagnosticos ---
cov = panel.drop(columns='release_month_approx').apply(lambda c: pd.Series({'n': c.notna().sum(),
        'first': c.first_valid_index(), 'last': c.last_valid_index(), 'sd': c.std(), 'min': c.min(), 'max': c.max()}))
cov.T.to_csv('out/fiscal_news_coverage.csv')
print(cov.T.to_string())
c = panel[['prisma_rev_primario_brl_mi_h1','focus_rev_primario_pp_h1','prisma_surp_primario_brl_mi']].dropna()
print('\ncorr prisma_rev_h1 (R$ mi) x focus_rev_h1 (pp):', round(c.iloc[:,0].corr(c.iloc[:,1]),3), 'n=',len(c))
print('corr surpresa mensal x focus_rev_h0:', round(panel.prisma_surp_primario_brl_mi.corr(panel.focus_rev_primario_pp_h0),3))
print('\nmaiores |surpresas mensais| (R$ mi):')
print(panel.prisma_surp_primario_brl_mi.dropna().abs().sort_values(ascending=False).head(8).index.strftime('%Y-%m').tolist())
print(panel.prisma_surp_primario_brl_mi.reindex(panel.prisma_surp_primario_brl_mi.dropna().abs().sort_values(ascending=False).head(8).index).round(0).to_string())
print('\nmaiores |rev Focus primario h1| (pp):')
x = panel.focus_rev_primario_pp_h1.dropna(); print(x.reindex(x.abs().sort_values(ascending=False).head(8).index).round(2).to_string())
