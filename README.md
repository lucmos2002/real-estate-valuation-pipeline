# real-estate-valuation-pipeline
Pipeline end-to-end de web scraping, tratamento de dados (POO) e modelagem preditiva imobiliária (LightGBM).

1. **Coleta (`src/scraping/collector.py`):** Web scraper com suporte a rotação de User-Agent, bypassing antibot (`undetected-chromedriver`), gestão de cookies e checkpoints de sessão.
2. **Engenharia de Dados (`src/etl/processor.py`):** Processamento orientado a objetos (`ProcessadorImobiliarioMestre`) para normalização de logradouros, de-duplicação e extração de taxas.
3. **Modelagem Preditiva (`src/modeling/evaluator.py`):** Modelo de gradient boosting (`LightGBM`) ajustado para precificação de mercado baseada em localização espacial e atributos do imóvel.

## 📊 Métricas de Avaliação
- **MAE Financeiro Misto:** Medição do erro financeiro médio absoluto por contrato.
- **WAPE Ponderado:** Erro percentual ponderado para mitigação de distorções em imóveis atípicos.

## 🛠️ Tecnologias Utilizadas
`Python` | `Pandas` | `Selenium` | `LightGBM` | `SQLAlchemy` | `SQL Server`
