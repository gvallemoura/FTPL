library(tesourotransparente)
library(tidyverse)
library(lubridate)

# 1. Coletar e tratar dados de Emissões
# Filtramos apenas os tipos que seu projeto exige 
emissoes <- tesouro_pegar_historico_leiloes() %>%
  mutate(data = as.Date(data_emissao)) %>%
  filter(tipo_titulo %in% c("LTN", "NTN-B", "LFT")) %>%
  group_by(data, tipo_titulo) %>%
  summarise(valor_emitido = sum(valor_emitido, na.rm = TRUE), .groups = 'drop')

# 2. Coletar e tratar dados de Resgates
resgates <- tesouro_pegar_historico_resgates() %>%
  mutate(data = as.Date(data_resgate)) %>%
  filter(tipo_titulo %in% c("LTN", "NTN-B", "LFT")) %>%
  group_by(data, tipo_titulo) %>%
  summarise(valor_resgatado = sum(valor_resgatado, na.rm = TRUE), .groups = 'drop')

# 3. Cálculo da Emissão Líquida mensal [cite: 113]
# O join é feito por data e tipo para alinhar os fluxos
dados_emissao <- emissoes %>%
  full_join(resgates, by = c("data", "tipo_titulo")) %>%
  mutate(
    valor_emitido = replace_na(valor_emitido, 0),
    valor_resgatado = replace_na(valor_resgatado, 0),
    emissao_liquida = valor_emitido - valor_resgatado
  ) %>%
  group_by(mes = floor_date(data, "month"), tipo_titulo) %>%
  summarise(I_t = sum(emissao_liquida), .groups = 'drop') %>%
  pivot_wider(names_from = tipo_titulo, values_from = I_t, values_fill = 0)

# Nota: Para finalizar a normalização pelo PIB (Seção 4, Tabela 1), 
# você precisaria fazer um left_join com a série do PIB do SGS/BCB.