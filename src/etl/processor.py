import pandas as pd
import re
import os
import csv

class ProcessadorImobiliarioMestre:
    def __init__(self, caminho_entrada: str):
        self.caminho_entrada = caminho_entrada
        if os.path.exists(caminho_entrada):
            self.df = pd.read_csv(caminho_entrada, sep=',', encoding='utf-8-sig', quoting=csv.QUOTE_MINIMAL, on_bad_lines='skip')
            print(f"📖 Base inicial: {len(self.df)} registros.")
        else:
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho_entrada}")

    def padronizar_texto_logradouro(self, texto):
        """Converte abreviações em nomes completos e ajusta para Title Case."""
        if not texto: return None
        
        # Mapa de substituições (Regex para garantir que mude apenas o início da palavra)
        substituicoes = {
            r'^[Rr]\b\.?': 'Rua',
            r'^[Aa][Vv]\b\.?': 'Avenida',
            r'^[Aa][Ll]\b\.?': 'Alameda',
            r'^[Pp][Cc]\b\.?': 'Praça',
            r'^[Tt][Vv]\b\.?': 'Travessa',
            r'^[Rr][Dd]\b\.?': 'Rodovia',
            r'^[Ee][Ss][Tt][Rr]\b\.?': 'Estrada'
        }
        
        novo_texto = texto.strip()
        for padrao, substituto in substituicoes.items():
            novo_texto = re.sub(padrao, substituto, novo_texto)
        
        # Converte para "Nome Próprio" (Ex: RUA DA VARZEA -> Rua Da Varzea)
        # O .title() funciona bem, mas o .capitalize() em cada palavra é mais seguro
        return " ".join([w.capitalize() if len(w) > 2 else w.lower() for w in novo_texto.split()])

    def extrair_area(self, texto):
        if pd.isna(texto) or texto == "": return None
        match = re.search(r'([\d\.,]+)\s*(?:m²|m2|m\b|M2|M²)', str(texto), re.IGNORECASE)
        if match:
            try:
                val = match.group(1).replace('.', '').replace(',', '.')
                return float(val)
            except: return None
        return None

    def extrair_taxas(self, texto):
        if not isinstance(texto, str) or pd.isna(texto) or texto == "": 
            return pd.Series([None, None])
        valores = re.findall(r'r\$\s*([\d\.]+)', texto.lower())
        valores = [float(v.replace('.', '')) for v in valores]
        condo, iptu = None, None
        texto_low = texto.lower()
        if 'condom' in texto_low and len(valores) > 0:
            condo = valores[0]
        if 'iptu' in texto_low:
            iptu = valores[1] if len(valores) > 1 else (valores[0] if 'condom' not in texto_low else None)
        return pd.Series([condo, iptu])

    def tratar_endereco_ultra_resiliente(self, texto):
        rua, numero, bairro, cidade = None, "S/N", None, None
        if pd.isna(texto) or texto == "": return pd.Series([None, None, None, None])

        # Normalização de vírgulas e espaços
        t = re.sub(r',+', ',', str(texto))
        t = re.sub(r'\s+', ' ', t).strip()

        # TENTATIVA 1: Padrão com Hífen
        if ' - ' in t:
            partes_hifen = t.split(' - ')
            logradouro = partes_hifen[0].strip()
            localidade = [p.strip() for p in partes_hifen[1].split(',') if p.strip()]
            
            if ',' in logradouro:
                p_rua = [i.strip() for i in logradouro.split(',') if i.strip()]
                rua = p_rua[0]
                if len(p_rua) > 1 and any(c.isdigit() for c in p_rua[1]): 
                    numero = p_rua[1]
            else:
                rua = logradouro
            if len(localidade) >= 1: bairro = localidade[0]
            if len(localidade) >= 2: cidade = localidade[1]

        # TENTATIVA 2: Padrão apenas com Vírgulas (Rodovias/Casos Especiais)
        else:
            partes = [p.strip() for p in t.split(',') if p.strip()]
            if len(partes) >= 3:
                rua = partes[0]
                if any(c.isdigit() for c in partes[1]):
                    numero, bairro, cidade = partes[1], partes[2], (partes[3] if len(partes) > 3 else None)
                else:
                    bairro, cidade = partes[1], partes[2]
            elif len(partes) == 2:
                rua, cidade = partes[0], partes[1]

        # Padronização Estética (R. -> Rua / CAIXA ALTA -> Title)
        if rua: rua = self.padronizar_texto_logradouro(rua)
        if bairro: bairro = bairro.title()
        if cidade: cidade = cidade.title()
            
        if not rua or len(rua) < 3: rua = None
        return pd.Series([rua, numero, bairro, cidade])

    def classificar_tipo(self, texto):
        mapa = {'loja': 'Loja', 'salao': 'Salão', 'salão': 'Salão', 'escritorio': 'Escritório',
                'conjunto': 'Conjunto Comercial', 'cj.comercial': 'Conjunto Comercial','galpão':'Galpão',
                'andar': 'Andar', 'sala': 'Sala Comercial', 'galpao': 'Galpão', 'hotel':'Hotel','Imovel':'Ponto Comercial',
                'predio': 'Prédio Comercial', 'casa': 'Casa Comercial', 'terreno': 'Terreno'}
        txt = str(texto).lower()
        for k, v in mapa.items():
            if k in txt: return v
        return "Outro"

    def processar(self, output_name):
        print("🚀 Iniciando processamento com padronização estética...")

        # 1. ÁREA: Extrair e ELIMINAR nulos
        self.df['Área'] = self.df['informacao'].apply(self.extrair_area)
        self.df = self.df.dropna(subset=['Área'])

        # 2. ENDEREÇO: Tratar, Padronizar (R., Av., Al.) e ELIMINAR sem Rua/Bairro/Cidade
        self.df[['Rua', 'Número', 'Bairro', 'Cidade']] = self.df['endereco'].apply(self.tratar_endereco_ultra_resiliente)
        self.df = self.df.dropna(subset=['Rua', 'Bairro'])

        # 3. TAXAS: Separar Condomínio e IPTU
        self.df[['Condomínio', 'IPTU']] = self.df['taxas'].apply(self.extrair_taxas)

        # 4. COMPLEMENTOS: Tipo de Imóvel e UF
        self.df['Tipo de Imóvel'] = self.df['informacao'].apply(self.classificar_tipo)
        self.df['UF'] = self.df['url'].apply(lambda x: re.search(r'-([a-zA-Z]{2})/\d+$', str(x)).group(1).upper() if re.search(r'-([a-zA-Z]{2})/\d+$', str(x)) else "")

        # 5. DEDUPLICAÇÃO FINAL
        antes = len(self.df)
        self.df.drop_duplicates(subset=['url'], keep='first', inplace=True)
        print(f"✅ Deduplicação: Removidos {antes - len(self.df)} duplicados.")

        self.df.to_csv(output_name, sep=';', index=False, encoding='utf-8-sig')
        print(f"🏁 Concluído! Planilha Final com endereços padronizados: {output_name}")

if __name__ == "__main__":
    p = ProcessadorImobiliarioMestre('imoveisweb_data_pt1.csv')
    p.processar('imoveisweb_data_pt1_v8.csv')
