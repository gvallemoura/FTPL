# Requisitos de dados ANBIMA

## 1. Objetivo

Este documento especifica os dados de curva de juros necessários para a Etapa B
do projeto empírico sobre denominação da dívida pública brasileira, FTPL e
inflação. O objetivo é construir controles de curva predeterminados para a
equação mensal de emissões por bloco de instrumento:

- N: LTN + NTN-F;
- F: LFT;
- R: NTN-B.

Esta etapa coleta, padroniza, transforma e integra dados da ANBIMA. Ela não
estima a equação de emissão.

## 2. Fontes e prioridade

A fonte preferencial é a API oficial ANBIMA Developers para curvas soberanas
zero-cupom:

- documentação: <https://developers.anbima.com.br/pt/apis/feed/precos-indices/titulos-publicos/>;
- endpoint esperado: `/feed/precos-indices/v1/titulos-publicos/curva-intradiaria`.

O endpoint, os parâmetros e o formato efetivos devem ser confirmados na
documentação vigente e nas credenciais fornecidas pela ANBIMA. O projeto não
deve assumir que o formato da resposta permaneceu inalterado.

Ordem de preferência:

1. API autenticada da ANBIMA;
2. arquivo local oficial em CSV, XLS, XLSX, JSON ou Parquet;
3. preenchimento manual auditável a partir de arquivo oficial.

Não devem ser usados dados inventados, fontes secundárias ou extrapolações da
curva. Ausência de acesso à API deve ser registrada, não tratada como ausência
econômica da série.

## 3. Cobertura e frequência

O painel mensal cobre, na última execução documentada, `1979-12` a
`2026-06`. A curva ANBIMA provavelmente não cobrirá todo esse período. A
cobertura efetiva deve ser preservada e reportada, sem preencher artificialmente
os meses anteriores ao início da série.

A entrada ideal é diária, com uma observação por data, tipo de curva e vértice.
Se houver mais de uma observação intradiária, a regra de seleção deve ser
documentada e o arquivo bruto deve ser preservado.

## 4. Dicionário da base diária longa

Arquivo de saída:

`data/intermediate/anbima/anbima_yield_curves_daily_long.csv`

| Coluna | Requisito |
|---|---|
| `date` | Data de referência, normalizada sem horário. |
| `curve_type` | `PRE`, `IPCA` ou `BEI`. |
| `vertex_du` | Prazo do vértice em dias úteis, positivo. |
| `yield_pct` | Taxa anual em percentual; 10,5% deve ser `10.5`. |
| `source` | API, arquivo local oficial ou template manual. |
| `download_timestamp` | Momento do download, preferencialmente UTC. |
| `source_file` | Caminho relativo ou nome do arquivo de origem. |
| `interpolated` | `True` se interpolado em prazo, `False` se observado. |

Arquivos brutos devem ser preservados em `data/raw/anbima/`, especialmente em
`data/raw/anbima/api/`. Arquivos existentes não devem ser sobrescritos.

## 5. Tipos de curva

- `PRE`: curva nominal prefixada;
- `IPCA`: curva real indexada ao IPCA;
- `BEI`: inflação implícita, fornecida diretamente ou calculada.

O parser pode mapear rótulos como prefixado, nominal, LTN e NTN-F para `PRE`;
real, IPCA e NTN-B para `IPCA`; e breakeven ou inflação implícita para `BEI`.
A conversão da nomenclatura original deve ser registrada no audit file quando
não for explícita.

## 6. Vértices-alvo

| Nome | Dias úteis |
|---|---:|
| `3m` | 63 |
| `6m` | 126 |
| `1y` | 252 |
| `2y` | 504 |
| `3y` | 756 |
| `5y` | 1260 |
| `7y` | 1764 |
| `10y` | 2520 |

Se a fonte fornecer outros vértices, aplicar interpolação linear em
`vertex_du`, separadamente por data e tipo de curva, somente dentro do
intervalo observado naquele dia. Não extrapolar. Marcar a observação com
`interpolated = True` e descrever a operação no audit file.

Arquivo wide diário:

`data/intermediate/anbima/anbima_yield_curves_daily_wide.csv`

## 7. Variáveis derivadas

Criar, quando disponíveis, os vértices `3m`, `6m`, `1y`, `2y`, `3y`,
`5y`, `7y` e `10y` para cada curva:

- `pre_3m` até `pre_10y`;
- `ipca_3m` até `ipca_10y`;
- `bei_3m` até `bei_10y`.

Calcular BEI somente na mesma data e no mesmo vértice:

```text
BEI_h = PRE_h - IPCA_h
```

Se uma curva oficial `BEI` estiver disponível e for compatível, preservar a
origem e registrar se o valor foi observado ou calculado.

Features simples, aplicadas aos blocos PRE, IPCA e BEI:

```text
level_5y = x_5y
slope_5y_1y = x_5y - x_1y
slope_10y_2y = x_10y - x_2y
curvature_1y_5y_10y = 2 * x_5y - x_1y - x_10y
```

Para PRE, por exemplo, os nomes são `pre_level_5y`,
`pre_slope_5y_1y` e `pre_curvature_1y_5y_10y`. O arquivo diário de features
é `data/intermediate/anbima/anbima_yield_curve_features_daily.csv`.

## 8. Agregação mensal predeterminada

O painel usa `month` no formato `YYYY-MM-01`. Para o mês `t`, utilizar
somente informação anterior a `t`.

### Última observação anterior

Selecionar a última observação diária disponível até o fim de `t-1`. Esta é a
versão principal e recebe o sufixo `_eom_lag1`, por exemplo:

- `pre_level_5y_eom_lag1`;
- `pre_slope_5y_1y_eom_lag1`;
- `ipca_level_5y_eom_lag1`;
- `bei_level_5y_eom_lag1`.

### Média do mês anterior

Calcular a média das observações diárias de `t-1`, com sufixo
`_avg_lag1`. Não usar a média ou o último valor do próprio mês `t`.

Arquivo mensal:

`data/intermediate/anbima/anbima_yield_curve_features_monthly.csv`

## 9. PCA alternativo

Estimar PCA separadamente, inicialmente com a versão `eom_lag1`, para:

- PRE: `pre_1y`, `pre_2y`, `pre_3y`, `pre_5y`, `pre_7y`, `pre_10y`;
- IPCA: `ipca_1y`, `ipca_2y`, `ipca_3y`, `ipca_5y`, `ipca_7y`, `ipca_10y`;
- BEI: `bei_1y`, `bei_2y`, `bei_3y`, `bei_5y`, `bei_7y`, `bei_10y`.

Padronizar as variáveis antes do PCA. Criar, quando houver dados suficientes,
até três componentes por bloco:

```text
pre_pc1_eom_lag1, pre_pc2_eom_lag1, pre_pc3_eom_lag1
ipca_pc1_eom_lag1, ipca_pc2_eom_lag1, ipca_pc3_eom_lag1
bei_pc1_eom_lag1, bei_pc2_eom_lag1, bei_pc3_eom_lag1
```

Criar também a versão `_avg_lag1` quando possível. O código oferece:

- `PCA_FULL_SAMPLE = True`: versão exploratória;
- `PCA_EXPANDING_WINDOW = True`: loadings estimados recursivamente;
- `MIN_PCA_WINDOW = 60`: janela mínima da versão recursiva.

Com poucas observações ou muitas lacunas, reduzir o número de componentes ou
deixar os fatores ausentes, sempre com aviso explícito.

## 10. API, autenticação e segurança

Credenciais nunca devem ser gravadas no código ou no Git. O script procura:

- `ANBIMA_ACCESS_TOKEN`;
- `ANBIMA_CLIENT_ID`;
- `ANBIMA_CLIENT_SECRET`;
- `ANBIMA_TOKEN_URL`;
- `ANBIMA_API_BASE`;
- `ANBIMA_CURVA_INTRADIARIA_PATH`, opcional.

Sem credenciais ou endpoint configurado, o script procura arquivos locais e,
se necessário, cria ou preserva o template manual. Respostas da API devem ser
salvas em `data/raw/anbima/api/` com nomes não destrutivos.

## 11. Template manual

Arquivo:

`data/raw/anbima/anbima_yield_curve_manual_template.csv`

Colunas obrigatórias:

| Coluna | Requisito |
|---|---|
| `date` | Data da curva, preferencialmente `YYYY-MM-DD`. |
| `curve_type` | `PRE`, `IPCA` ou `BEI`. |
| `vertex_du` | Vértice em dias úteis. |
| `yield_pct` | Taxa anual em percentual. |
| `source_document` | Documento ou arquivo oficial de origem. |
| `notes` | Página, tabela, unidade, conversão e observações. |

Deve haver uma linha por combinação de data, curva e vértice. Não preencher
valores ausentes sem fonte clara. As instruções mínimas também estão em
`data/raw/anbima/README_anbima_manual_template.txt`.

## 12. Integração e saídas

O painel estrutural original deve permanecer intacto. O painel derivado é:

`data/clean/ftpl_monthly_panel_with_yield_curve_controls.csv`

O merge é feito por `month`, preservando todas as observações do painel de
emissões. As listas de controles existentes são salvas em:

`data/diagnostics/yield_curve_control_lists.json`

Principais saídas intermediárias:

- `anbima_yield_curves_daily_long.csv`;
- `anbima_yield_curves_daily_wide.csv`;
- `anbima_yield_curve_features_daily.csv`;
- `anbima_yield_curve_features_monthly.csv`;
- `anbima_yield_curve_pca_factors_monthly.csv`.

## 13. Auditoria e critérios de aceitação

O audit file é:

`data/diagnostics/anbima_yield_curve_audit.csv`

Ele deve conter, no mínimo:

```text
date
curve_type
source
source_url
source_file
n_vertices_raw
n_vertices_used
interpolation_used
download_timestamp
notes
```

Cada observação ou lote deve ser rastreável à URL, documento, arquivo, data de
download, unidade e transformação aplicada. Também devem ser produzidos:

- `data/diagnostics/anbima_yield_curve_diagnostics.csv`;
- `data/diagnostics/anbima_yield_curve_pca_explained_variance.csv`;
- `data/diagnostics/anbima_yield_curve_pca_loadings.csv`;
- `data/diagnostics/yield_curve_control_lists.json`;
- gráficos em `data/figures/`.

Critérios mínimos:

1. datas válidas e ordenadas;
2. tipos de curva padronizados;
3. vértices positivos;
4. unidade de `yield_pct` documentada;
5. ausência de extrapolação;
6. BEI calculado somente para mesma data e vértice;
7. controles mensais usando somente o mês anterior;
8. fonte auditável;
9. painel original preservado;
10. NaNs reportados, não preenchidos silenciosamente.

## 14. Estado atual

A implementação está em
`src/build_anbima_yield_curve_controls.py`, com notebook auxiliar em
`notebooks/build_anbima_yield_curve_controls.ipynb`. A última execução
documentada encontrou ausência de credenciais ANBIMA e nenhum arquivo histórico
local utilizável. O template manual foi criado/preservado e as bases derivadas
foram geradas estruturalmente, mas sem observações substantivas de curva.

Assim, o painel integrado contém as colunas esperadas, mas os valores de curva
permanecem `NaN` até que dados autenticados ou dados manuais auditados sejam
fornecidos. O próximo passo é obter acesso à API ou preencher o template com
arquivos oficiais, preservando os documentos originais e completando a
auditoria.

## 15. Execução

A partir da raiz do projeto:

```bash
python3 src/build_anbima_yield_curve_controls.py
```

O script usa `pathlib.Path`, caminhos relativos ao repositório, cria os
diretórios necessários e é compatível com macOS e Google Colab, desde que as
dependências e, quando aplicável, as credenciais estejam disponíveis.

Documentos relacionados:

- `docs/DocumentacaoProjeto.tex`;
- `docs/Project.md`;
- `src/build_anbima_yield_curve_controls.py`;
- `data/raw/anbima/README_anbima_manual_template.txt`.


## 16. Alternativa de contingência (registrada, não implementada)

Esta seção registra uma alternativa a ser considerada **somente se** não for
possível obter a curva histórica ANBIMA pela API autenticada ou por arquivos
oficiais. Ela não está implementada e, se adotada, exige revisar a §2, que hoje
restringe a fonte à ANBIMA.

### Origem da ideia

Avaliação, em 2026-11-14, do MCP `tesourodireto-mcp`
(<https://github.com/msperlin/tesourodireto-mcp>, contraparte Python do pacote R
`GetTDData`):

- `get_yield_curve` raspa `https://www.anbima.com.br/informacoes/est-termo/CZ.asp`,
  mas só entrega a curva ETTJ **do dia corrente**. Teste com `Dt_Ref` em datas
  passadas (03/11/2025, 02/01/2015) retornou a página sem a tabela. Portanto, não
  resolve o histórico ANBIMA.
- Os dados históricos do MCP vêm do CSV oficial do Tesouro Transparente
  (`precotaxatesourodireto.csv`, dataset "Taxas dos Títulos Ofertados pelo
  Tesouro Direto"), diário, por título e vencimento, a partir de 2005.

### Proposta

Construir curvas zero-cupom aproximadas diretamente do CSV do Tesouro
Transparente (sem usar o MCP no pipeline, pois ele trunca séries diárias longas
em `max_rows`):

- `PRE`: taxas de **LTN** (zero-cupom prefixado);
- `IPCA`: taxas de **NTN-B Principal** (zero-cupom real);
- `BEI`: `PRE_h - IPCA_h`, mesma data e vértice;
- prazo em dias úteis pelo calendário ANBIMA (o pacote inclui
  `anbima_holidays.txt`, 2001–2079);
- interpolação linear em `vertex_du` somente dentro do intervalo observado,
  sem extrapolação, conforme a §6;
- identificação como fonte distinta (por exemplo, `source = TESOURO_DIRETO`),
  nunca misturada silenciosamente com a curva ANBIMA.

Implementação sugerida: baixar e preservar o CSV em
`data/raw/tesouro_direto/` com timestamp e criar uma função
`load_tesouro_direto_zero_curves()` em
`src/build_anbima_yield_curve_controls.py`, com prioridade abaixo da API e dos
arquivos locais ANBIMA. O resto do pipeline (interpolação, features,
`eom_lag1`/`avg_lag1`, PCA) já opera sobre a base diária longa.

### Limitações a documentar se adotada

- Taxas de varejo do Tesouro Direto (com spread em relação ao mercado
  secundário), não a ETTJ ANBIMA;
- LTNs raramente passam de ~4 a 7 anos: `pre_7y`, `pre_10y` e `bei_10y` ficarão
  muito incompletos; NTN-F tem cupom e não deve ser tratada como zero;
- vértices disponíveis variam com os títulos ofertados em cada data;
- sem cobertura antes de 2005.
