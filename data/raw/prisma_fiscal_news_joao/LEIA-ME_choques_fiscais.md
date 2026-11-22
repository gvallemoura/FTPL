# Séries de notícia fiscal (Prisma Fiscal e Focus)

Arquivo principal: `fiscal_news_monthly.csv` (uma linha por mês `month`, AAAA-MM-01).

## Colunas
| Coluna | Significado | Unidade |
|---|---|---|
| `realizado_primario` | Resultado primário do Governo Central realizado no mês `month` (serie-historica.xlsx) | R$ milhões |
| `prisma_fc_primario_m` | Mediana Prisma para o mês `month`, enviada no próprio mês `month` | R$ milhões |
| `prisma_surp_primario_brl_mi` | Surpresa = realizado − previsão Prisma. Mede **fluxo**, inclui receitas/despesas extraordinárias | R$ milhões |
| `release_month_approx` | Mês aproximado de divulgação do realizado (m+1). Conferir a data exata no Tesouro | data |
| `prisma_rev_primario_brl_mi_h{0..3}` | Revisão mensal da mediana Prisma do primário para o ano-alvo (h=0 ano corrente; h=1,2,3 anos seguintes); entre envios consecutivos | R$ milhões |
| `prisma_rev_dbgg_gc_pp_h*` | Idem, dívida bruta do Governo Central, % do PIB (2021–2026) | p.p. |
| `prisma_rev_dbgg_gg_pp_h*` | Idem, dívida bruta do Governo Geral, % do PIB (2015–2020; conceito diferente) | p.p. |
| `focus_rev_{primario,nominal,dlsp,dbgg}_pp_h*` | Variação mensal da mediana Focus (fim do mês) para o ano-alvo; primário/nominal e dívida líquida do setor público, dívida bruta do governo geral | p.p. do PIB |

## Cobertura
Ver `fiscal_news_coverage.csv`. Prisma: envios de dez/2015 a out/2026 (131). Focus: primário, nominal e DLSP desde 2012; DBGG desde 2018. Surpresa mensal: 111 meses (dez/2015 a ago/2026).

## Cuidados
1. **Normalização por PIB:** as variáveis Prisma estão em R$ milhões. Dividir por `pib_12m_lag1_brl` do painel do projeto na integração. O Focus já está em % do PIB.
2. **Conceitos distintos:** Prisma = Governo Central; Focus = setor público consolidado. Não são idênticos.
3. **Surpresa mensal ≠ notícia sobre o valor presente.** Mede fluxo e inclui itens extraordinários (por exemplo, jun/2020, dez/2023). As revisões de médio prazo (h≥1) são mais próximas de ΔPV(S).
4. **Correções aplicadas** (`prisma_corrections_log.csv`): rótulos de Dívida Bruta e Resultado Nominal trocados na aba Mai2025; mês de envio tomado do nome da aba, pois a célula "Mês de envio" está desatualizada em Ago2024, Out2024, Nov2024 e Out2026 (`prisma_sheet_audit.csv`).
5. **Focus:** `baseCalculo = 0` (confirmar a definição na documentação do BCB); último dia do mês; nov/2026 (parcial) excluído.
6. **Timing:** revisões Prisma de um mês dependem da data de corte da pesquisa; alinhar com a data do dado de inflação na estimação.
