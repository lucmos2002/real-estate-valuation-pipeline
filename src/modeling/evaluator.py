import pandas as pd
import numpy as np
import lightgbm as lgb
import urllib
from sqlalchemy import create_engine
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_percentage_error, mean_absolute_error

# =====================================================================
# TÓPICO 1: CONEXÃO COM A INSTÂNCIA EXPRESS E EXTRAÇÃO DA AMOSTRA
# =====================================================================
params = urllib.parse.quote_plus(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=PTR-PE0DBPGS\SQLEXPRESS;"
    "DATABASE=geoimob;"
    "Trusted_Connection=yes;"
)
string_conexao = f"mssql+pyodbc:///?odbc_connect={params}"
engine = create_engine(string_conexao)

print("=== 1. EXTRAINDO 10% DA TABELA dbo.imovel_vacancia ===")

query = """
    SELECT 
        id, Tipo_de_Imóvel, Área, Valor, IPTU, Condomínio,
        latitude_decimal, longitude_decimal, Cidade_norm, 
        Bairro_norm, ordem_faixa_area 
    FROM dbo.imovel_vacancia TABLESAMPLE (10 PERCENT)
    WHERE Valor IS NOT NULL AND Área > 0;
"""
df = pd.read_sql(query, con=engine)
print(f"Base carregada com sucesso. Volumetria da amostra: {len(df)} linhas.")

# =====================================================================
# TÓPICO 2: ENGENHARIA DE ATRIBUTOS E NORMALIZAÇÃO POR M²
# =====================================================================
print("\n=== 2. EXECUTANDO TIPAGEM E CÁLCULO DE RÁCIOS DE MERCADO ===")

for col in ['latitude_decimal', 'longitude_decimal']:
    if df[col].dtype == 'object':
        df[col] = df[col].astype(str).str.replace(',', '.').astype(float)

df['IPTU'] = pd.to_numeric(df['IPTU'], errors='coerce').fillna(0)
df['Condomínio'] = pd.to_numeric(df['Condomínio'], errors='coerce').fillna(0)
df['Área'] = df['Área'].astype(float)
df['Valor'] = df['Valor'].astype(float)

# Alvo da modelagem intensiva: Valor por Metro Quadrado legítimo
df['Valor_m2_real'] = df['Valor'] / df['Área']
df['iptu_por_m2'] = df['IPTU'] / df['Área']
df['condominio_por_m2'] = df['Condomínio'] / df['Área']

df = df.dropna(subset=['latitude_decimal', 'longitude_decimal']).reset_index(drop=True)

# =====================================================================
# TÓPICO 3: APRENDIZADO ESPACIAL ESTRATIFICADO (KNN POR TIPO)
# =====================================================================
print("\n=== 3. COMPUTANDO ASSINATURA GEOGRÁFICA ESTRATIFICADA POR TIPO ===")

from sklearn.neighbors import KNeighborsRegressor

# Inicialização da coluna da proxy zerada para receber os blocos isolados
df['proxy_preco_bairro_m2'] = 0.0

# LOOP DE ISOLAMENTO: O KNN opera de forma independente para cada categoria de ativo
for tipo in df['Tipo_de_Imóvel'].unique():
    mask_tipo = df['Tipo_de_Imóvel'] == tipo
    df_sub = df[mask_tipo]
    
    # Define uma vizinhança segura adaptada ao tamanho do cluster da categoria
    n_vizinhos = min(15, max(3, len(df_sub) // 4))
    
    if len(df_sub) >= 3:
        coords_rad_sub = np.radians(df_sub[['latitude_decimal', 'longitude_decimal']])
        
        knn_tipo = KNeighborsRegressor(
            n_neighbors=n_vizinhos, 
            weights='distance', 
            algorithm='ball_tree', 
            metric='haversine'
        )
        knn_tipo.fit(coords_rad_sub, df_sub['Valor_m2_real'])
        
        # Mapeamento geográfico purista, livre de contaminação cruzada de outras tipologias
        df.loc[mask_tipo, 'proxy_preco_bairro_m2'] = knn_tipo.predict(coords_rad_sub)
    else:
        # Fallback de segurança estatística caso haja pouquíssimos registos do tipo na amostra
        df.loc[mask_tipo, 'proxy_preco_bairro_m2'] = df_sub['Valor_m2_real'].median() if len(df_sub) > 0 else df['Valor_m2_real'].median()

# Configuração das variáveis categóricas estruturadas para o LightGBM
for col in ['Tipo_de_Imóvel', 'Cidade_norm', 'Bairro_norm']:
    df[col] = df[col].astype('category')

features = ['Tipo_de_Imóvel', 'Área', 'iptu_por_m2', 'condominio_por_m2', 
            'latitude_decimal', 'longitude_decimal', 'proxy_preco_bairro_m2']

X = df[features]
y = np.log1p(df['Valor_m2_real'])  # Atenuação de assimetria à direita (cauda longa)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Hiperparâmetros calibrados para evitar avisos de divisões inválidas (best gain: -inf)
modelo_espacial = lgb.LGBMRegressor(
    objective='regression',
    n_estimators=1200,
    learning_rate=0.02,
    max_depth=7,
    num_leaves=31,
    min_child_samples=30,
    random_state=42,
    verbose=-1
)
modelo_espacial.fit(X_train, y_train)

# =====================================================================
# TÓPICO 4: RETORNO À ESCALA NOMINAL, FORMATAÇÃO PT-BR E EXPORTAÇÃO
# =====================================================================
print("\n=== 4. EXECUTANDO AVALIAÇÃO MULTIMÉTRICA E FORMATAÇÃO DE APRESENTAÇÃO ===")

preds_log = modelo_espacial.predict(X_test)
preds_m2 = np.expm1(preds_log)
y_test_m2 = np.expm1(y_test)

area_teste = X_test['Área'].values
valor_total_predito = preds_m2 * area_teste
valor_total_real = y_test_m2 * area_teste

mae_financeiro = mean_absolute_error(valor_total_real, valor_total_predito)
wape_real = (np.sum(np.abs(valor_total_real - valor_total_predito)) / np.sum(valor_total_real)) * 100

print(f"  ✔ MAE Financeiro Médio Ajustado: R$ {mae_financeiro:.2f} por contrato")
print(f"  ✔ WAPE Real Ponderado (KNN Estratificado): {wape_real:.2f}%")

# Geração das predições estruturadas na base completa da amostra de 10%
df['Valor_m2_predito'] = np.expm1(modelo_espacial.predict(X))
df['Valor_Predito_Justo'] = df['Valor_m2_predito'] * df['Área']
df['Diferenca_Absoluta'] = df['Valor'] - df['Valor_Predito_Justo']
df['Descolamento_Percentual'] = (df['Diferenca_Absoluta'] / df['Valor']) * 100

df_seguranca = df[[
    'id', 'Tipo_de_Imóvel', 'Cidade_norm', 'Bairro_norm', 'Área', 
    'Valor', 'Valor_Predito_Justo', 'Diferenca_Absoluta', 'Descolamento_Percentual', 
    'Valor_m2_real', 'Valor_m2_predito'
]].copy()

colunas_formatar = [
    'Área', 'Valor', 'Valor_Predito_Justo', 'Diferenca_Absoluta', 
    'Descolamento_Percentual', 'Valor_m2_real', 'Valor_m2_predito'
]

# Conversão cosmética final para visualização correta e direta no Excel (padrão PT-BR)
for col in colunas_formatar:
    df_seguranca[col] = df_seguranca[col].apply(lambda x: f"{x:.2f}".replace('.', ','))

nome_arquivo_csv = "amostra_predicoes_10_porcento.csv"
df_seguranca.to_csv(nome_arquivo_csv, index=False, sep=';', encoding='utf-8-sig')
print(f"\nArquivo '{nome_arquivo_csv}' gerado com sucesso com KNN Estratificado!")
