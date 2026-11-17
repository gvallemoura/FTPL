Você está trabalhando no meu projeto empírico sobre denominação da dívida pública brasileira, FTPL e inflação.

Estou no diretório local do projeto no macOS. O diretório contém os códigos e arquivos gerados a partir de um notebook Python que constrói uma base mensal com emissões brutas por instrumento, estoques, vencimentos, variáveis macro e normalizações por PIB.

Seu objetivo é implementar a próxima etapa do pipeline: construção das variáveis estruturais da Etapa A, que entrarão fora de qualquer PCA na equação de previsão das emissões.

A equação de referência é:

g_t^j = alpha^j + delta_0^j m_{t|t-1}^j + delta_1^j m_{t+1|t-1}^j + Lambda^{j'} Z_{t-1} + mu_{m(t)}^j + u_t^j,

para j em {N,F,R}, onde:
- N = LTN + NTN-F;
- F = LFT;
- R = NTN-B.

Essas variáveis devem capturar informação predeterminada disponível antes da decisão de emissão do mês t.

Antes de escrever código, faça o seguinte:
1. Inspecione a estrutura do diretório.
2. Identifique o notebook principal, scripts Python existentes e arquivos CSV já gerados.
3. Localize o painel mensal mais recente. Ele provavelmente estará em algo como:
   - data/clean/ftpl_monthly_panel.csv
   - data/clean/ftpl_monthly_panel_with_pib_normalization.csv
   - ou arquivo similar.
4. Leia os nomes das colunas disponíveis e adapte o código a elas.
5. Não apague nem sobrescreva arquivos originais sem criar backups ou novos arquivos derivados.

Crie uma nova etapa do pipeline com os seguintes entregáveis:

1. Um script Python chamado, por exemplo:

   build_structural_controls.py

2. Um notebook auxiliar, se for conveniente, chamado:

   build_structural_controls.ipynb

3. Um arquivo CSV final:

   data/clean/ftpl_monthly_panel_structural_controls.csv

4. Templates manuais, caso os dados não estejam disponíveis automaticamente:

   data/raw/paf_manual_targets.csv
   data/raw/treasury_liquidity_reserve_manual.csv

5. Diagnósticos e gráficos em:

   data/diagnostics/
   data/figures/

O código deve ser modular, comentado, robusto a colunas ausentes e compatível com Google Colab e execução local no macOS.

------------------------------------------------------------
Parte 1 — Variáveis estruturais básicas
------------------------------------------------------------

A partir do painel mensal existente, construa variáveis defasadas.

1. Emissões defasadas

Usar as variáveis normalizadas por PIB, se existirem:

g_N_pib
g_F_pib
g_R_pib
g_total_NFR_pib

Criar:

g_N_pib_lag1
g_F_pib_lag1
g_R_pib_lag1
g_total_NFR_pib_lag1

e também lag2 e lag3, com número de defasagens configurável:

N_LAGS_ISSUANCE = 3

Criar médias móveis usando apenas informação até t-1:

g_N_pib_ma3_lag1
g_F_pib_ma3_lag1
g_R_pib_ma3_lag1

2. Participações no estoque defasadas

A partir de:

share_N
share_F
share_R

criar:

share_N_lag1
share_F_lag1
share_R_lag1

Criar diagnóstico para verificar se share_N + share_F + share_R soma aproximadamente 1.

3. Estoques defasados

A partir de:

stock_N_brl
stock_F_brl
stock_R_brl

criar:

stock_N_brl_lag1
stock_F_brl_lag1
stock_R_brl_lag1
stock_total_NFR_brl_lag1

Se pib_12m_lag1_brl existir, criar também:

stock_N_pib_lag1
stock_F_pib_lag1
stock_R_pib_lag1
stock_total_NFR_pib_lag1

4. Vencimentos agregados e janelas futuras

Usar as variáveis de vencimentos normalizadas por PIB, se existirem:

m_N_pib
m_F_pib
m_R_pib
m_total_NFR_pib

Criar:

m_total_NFR_pib_lag0
m_total_NFR_pib_lead1
m_total_NFR_pib_window_3m
m_total_NFR_pib_window_6m
m_total_NFR_pib_window_12m

A janela deve ser:

M_{t:t+K|t-1}^{total} = soma de M_{t+k|t-1}^{total}, k=0,...,K.

Também criar, se possível:

m_N_pib_window_3m
m_F_pib_window_3m
m_R_pib_window_3m

Deixe comentário claro no código explicando que essas janelas só são interpretáveis como predeterminadas se o cronograma de vencimentos futuro já era conhecido em t-1.

------------------------------------------------------------
Parte 2 — Dummies de calendário e eventos
------------------------------------------------------------

Criar:

year
quarter
calendar_month

Não precisa criar automaticamente 12 dummies de mês se for mais limpo usar C(calendar_month) depois na regressão, mas crie a variável calendar_month.

Criar dummies configuráveis para episódios relevantes:

dummy_global_financial_crisis: 2008-09 a 2009-06
dummy_taper_tantrum: 2013-05 a 2013-12
dummy_domestic_recession_2015_2016: 2015-01 a 2016-12
dummy_truckers_strike: 2018-05
dummy_covid: 2020-03 a 2021-12
dummy_election_uncertainty: meses de outubro a dezembro em anos eleitorais presidenciais, inicialmente 2002, 2006, 2010, 2014, 2018, 2022

Deixe essas datas no topo do código em um dicionário, para que eu possa alterar facilmente.

------------------------------------------------------------
Parte 3 — Dummies de operações extraordinárias
------------------------------------------------------------

Procure o arquivo:

auction_operations_clean.csv

Ele deve conter a base limpa de leilões.

Se o arquivo existir, agregue por mês operações extraordinárias:

- Extra Venda
- Extra Compra
- Compra
- Troca, se identificável
- recompra ou buyback, se identificável

Crie dummies mensais:

dummy_extra_sale
dummy_extra_purchase
dummy_exchange_operation
dummy_buyback_operation

Crie também medidas de intensidade, se possível:

extra_sale_value_brl
extra_sale_value_pib
extra_purchase_value_brl
extra_purchase_value_pib
buyback_value_brl
buyback_value_pib
exchange_value_brl
exchange_value_pib

Use pib_12m_lag1_brl para normalizar por PIB quando disponível.

Crie versões defasadas dessas dummies e intensidades, com sufixo lag1.

Se não for possível identificar troca de forma confiável, deixe comentário no código e crie apenas as variáveis que puder identificar com segurança.

------------------------------------------------------------
Parte 4 — Variáveis do PAF
------------------------------------------------------------

O Plano Anual de Financiamento — PAF — deve ser codificado como fonte institucional predeterminada.

Não dependa exclusivamente de OCR automático de PDFs. Prefira criar uma base manual auditável.

Verifique se existe:

data/raw/paf_manual_targets.csv

Se não existir, crie um template com as seguintes colunas:

year
publication_date
valid_from
valid_to
paf_prefixado_min
paf_prefixado_max
paf_selic_min
paf_selic_max
paf_price_indexed_min
paf_price_indexed_max
paf_fx_min
paf_fx_max
paf_maturing_12m_min
paf_maturing_12m_max
paf_avg_maturity_min
paf_avg_maturity_max
paf_stock_min_brl
paf_stock_max_brl
paf_strategy_prefixado
paf_strategy_selic
paf_strategy_price_indexed
paf_strategy_fx
source_document
notes

As participações devem estar em proporção. Exemplo: 35% deve ser 0.35.

Se o arquivo já existir e tiver dados preenchidos, faça merge por data, usando valid_from e valid_to quando disponíveis. Se só houver year, faça merge por ano.

Mapeamento para os grupos do artigo:

N = prefixado
F = Selic / taxa flutuante
R = índice de preços

Crie:

paf_N_target = (paf_prefixado_min + paf_prefixado_max)/2
paf_F_target = (paf_selic_min + paf_selic_max)/2
paf_R_target = (paf_price_indexed_min + paf_price_indexed_max)/2

Crie larguras de banda:

paf_N_band_width
paf_F_band_width
paf_R_band_width

Usando share_N_lag1, share_F_lag1 e share_R_lag1, crie:

paf_gap_N_lag1 = share_N_lag1 - paf_N_target
paf_gap_F_lag1 = share_F_lag1 - paf_F_target
paf_gap_R_lag1 = share_R_lag1 - paf_R_target

Crie distâncias aos limites:

paf_dist_N_to_lower_lag1 = share_N_lag1 - paf_prefixado_min
paf_dist_N_to_upper_lag1 = paf_prefixado_max - share_N_lag1

paf_dist_F_to_lower_lag1 = share_F_lag1 - paf_selic_min
paf_dist_F_to_upper_lag1 = paf_selic_max - share_F_lag1

paf_dist_R_to_lower_lag1 = share_R_lag1 - paf_price_indexed_min
paf_dist_R_to_upper_lag1 = paf_price_indexed_max - share_R_lag1

Crie dummies:

paf_N_below_band_lag1
paf_N_above_band_lag1
paf_F_below_band_lag1
paf_F_above_band_lag1
paf_R_below_band_lag1
paf_R_above_band_lag1

Converter estratégias qualitativas em dummies. Aceitar valores:

increase
decrease
stable
neutral
unclear

Criar:

paf_strategy_N_increase
paf_strategy_N_decrease
paf_strategy_N_stable

paf_strategy_F_increase
paf_strategy_F_decrease
paf_strategy_F_stable

paf_strategy_R_increase
paf_strategy_R_decrease
paf_strategy_R_stable

Se o campo estiver vazio, tratar como unclear.

Se existirem indicadores mensais de prazo médio ou percentual vincendo em 12 meses, criar gaps em relação ao PAF:

paf_gap_maturing_12m_lag1
paf_gap_avg_maturity_lag1

Caso contrário, apenas manter as metas do PAF no painel.

------------------------------------------------------------
Parte 5 — Reserva de liquidez do Tesouro
------------------------------------------------------------

A reserva de liquidez é um controle importante para pressão de caixa e necessidade de emissão.

Verifique se existe:

data/raw/treasury_liquidity_reserve_manual.csv

Se não existir, crie um template com:

month
liquidity_reserve_brl
liquidity_reserve_months_of_debt_service
source_document
notes

Se possível, tente localizar automaticamente a reserva de liquidez nos arquivos do Relatório Mensal da Dívida Pública Federal — RMD — e seus anexos no Tesouro Transparente. Use internet, mas preserve o template manual como fonte final auditável.

Se conseguir baixar automaticamente, salve também a fonte bruta e documente de onde veio.

Se liquidity_reserve_brl estiver disponível, crie:

liquidity_reserve_brl_lag1
liquidity_reserve_pib_lag1
liquidity_reserve_over_stock_lag1
liquidity_reserve_over_maturity_12m_lag1

Definições:

liquidity_reserve_pib_lag1 =
liquidity_reserve_brl_lag1 / pib_12m_lag1_brl

liquidity_reserve_over_stock_lag1 =
liquidity_reserve_brl_lag1 / stock_total_NFR_brl_lag1

liquidity_reserve_over_maturity_12m_lag1 =
liquidity_reserve_brl_lag1 / maturity_total_NFR_12m_brl_lag1

Se não houver maturity_total_NFR_12m_brl_lag1, use a melhor proxy disponível e documente no código.

A reserva de liquidez deve entrar defasada. Não use o valor contemporâneo em t como controle da emissão de t.

------------------------------------------------------------
Parte 6 — Listas finais de controles
------------------------------------------------------------

Ao final, crie duas listas Python.

1. structural_controls_base

Deve incluir apenas variáveis que existem no painel. Comece com:

g_N_pib_lag1
g_F_pib_lag1
g_R_pib_lag1
share_N_lag1
share_F_lag1
share_R_lag1
paf_gap_N_lag1
paf_gap_F_lag1
paf_gap_R_lag1
liquidity_reserve_pib_lag1
m_total_NFR_pib_window_3m

2. structural_controls_extended

Inclua:

- lags adicionais de emissão;
- médias móveis de emissão;
- dummies de crise;
- dummies de operações extraordinárias;
- dummies qualitativas do PAF;
- distâncias aos limites do PAF;
- reserva de liquidez sobre estoque;
- reserva de liquidez sobre vencimentos;
- janelas de vencimentos de 6 e 12 meses.

O código deve imprimir:
- variáveis incluídas;
- variáveis ausentes;
- número de observações não ausentes de cada variável.

------------------------------------------------------------
Parte 7 — Diagnósticos
------------------------------------------------------------

Produza diagnósticos obrigatórios:

1. tabela de valores ausentes das variáveis estruturais;
2. estatísticas descritivas;
3. matriz de correlação das variáveis estruturais principais;
4. gráfico das participações efetivas versus bandas do PAF, se o PAF estiver preenchido;
5. gráfico da reserva de liquidez normalizada, se disponível;
6. alerta para variáveis com menos de 50% de observações não ausentes;
7. alerta para variáveis constantes ou quase constantes.

Salvar diagnósticos em:

data/diagnostics/

Salvar gráficos em:

data/figures/

------------------------------------------------------------
Parte 8 — Estilo e segurança
------------------------------------------------------------

O código deve:

- não sobrescrever o painel original;
- criar panel_structural = panel.copy();
- funcionar mesmo quando PAF ou reserva de liquidez ainda estiverem vazios;
- criar templates se os dados não existirem;
- imprimir mensagens claras;
- usar pathlib.Path;
- evitar caminhos absolutos;
- ser compatível com macOS e Google Colab;
- usar apenas pandas, numpy, matplotlib, requests e bibliotecas padrão, salvo justificativa;
- ter docstrings nas funções principais.

Ao final, salve:

data/clean/ftpl_monthly_panel_structural_controls.csv

e imprima as dimensões do painel, período da amostra e as listas finais de controles.

Antes de finalizar, rode o script localmente, corrija erros e mostre um resumo dos arquivos criados.