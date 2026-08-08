# -*- coding: utf-8 -*-
import csv
import re
import time
import random
import os
import pickle
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException
)
from tqdm import tqdm

# --- LISTA DE USER-AGENTS PARA ROTAÇÃO ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
]

COOKIE_FILE = "cookies.pkl"
CSV_FILE = "imoveisweb_data_pt1.csv"
CHECKPOINT_FILE = "checkpoint_page.txt"
MAX_PAGES_TO_SCRAPE = 5000
PAGES_PER_BATCH = 1 
DRIVER_VERSION = 150 

CARD_SELECTOR = ".postingCard-module__posting-container a" 
COOKIE_BANNER_BUTTON_SELECTOR = "button[data-testid='action:understood-button']"

# --- FUNÇÃO PARA INICIALIZAR O DRIVER ---
def initialize_driver(load_cookies=False):
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')

    user_agent = random.choice(USER_AGENTS)
    print(f"Usando User-Agent: {user_agent}")
    options.add_argument(f"user-agent={user_agent}")

    driver = uc.Chrome(options=options, use_subprocess=True, version_main=DRIVER_VERSION)

    if load_cookies and os.path.exists(COOKIE_FILE):
        print("Carregando cookies salvos...")
        try:
            driver.get("https://www.imovelweb.com.br")
            time.sleep(2)
            with open(COOKIE_FILE, "rb") as f:
                cookies = pickle.load(f)
                for c in cookies: 
                    driver.add_cookie(c)
            driver.refresh()
        except Exception as e:
            print(f"Erro ao carregar cookies: {e}")
    return driver

# --- FUNÇÕES DE CHECKPOINT ---
def save_checkpoint(page_number):
    with open(CHECKPOINT_FILE, "w") as f: 
        f.write(str(page_number))

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f: 
                return int(f.read().strip())
        except: 
            return 1
    return 1

def handle_popups(driver):
    try:
        WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, COOKIE_BANNER_BUTTON_SELECTOR))
        ).click()
    except: 
        pass

# --- FUNÇÃO DE EXTRAÇÃO INTERNA CORRIGIDA ---
def extrair_dados_imovel(driver):
    wait = WebDriverWait(driver, 12)
    html_source = driver.page_source

    def safe_get_text_css(selector):
        try:
            element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            return element.text.strip()
        except: 
            return ""

    # 1. Valor do Aluguel via Regex Estruturado
    valor_aluguel = ""
    try:
        match_aluguel = re.search(r"'precioAlquiler':\s*\"(.*?)\"", html_source)
        if match_aluguel: 
            valor_aluguel = match_aluguel.group(1).strip()
    except: 
        pass

    # 2. Extração de Taxas (IPTU / Condomínio Corrigidos)
    taxas = safe_get_text_css(".price-expenses")
    if not taxas:
        taxas = safe_get_text_css("#article-container div.price-container-property div.price-extra span")
    if not taxas:
        try:
            texto_precos = safe_get_text_css(".price-container-property")
            match_taxas = re.search(r'(?:iptu|condomínio|taxas).*?R?\$\s*([\d.,]+)', texto_precos, re.IGNORECASE)
            if match_taxas: 
                taxas = match_taxas.group(0).strip()
        except: 
            pass

    taxas = " ".join(taxas.split())

    # 3. Extração da Área do Imóvel
    area = ""
    try:
        elemento_area = driver.find_element(By.CSS_SELECTOR, "li[title*='m²'], span[title*='m²']")
        area = elemento_area.text.strip()
    except:
        try:
            # Fallback por busca de texto que contenha m² nos itens de lista
            elementos_li = driver.find_elements(By.CSS_SELECTOR, "#article-container ul li")
            for li in elementos_li:
                if "m²" in li.text:
                    area = li.text.strip()
                    break
        except:
            pass
            
    if not area:
        try:
            titulo_texto = safe_get_text_css("#article-container hgroup h1")
            match_area = re.search(r'(\d+[\d.,]*)\s*m²', titulo_texto)
            if match_area: 
                area = f"{match_area.group(1)} m²"
            else:
                area = "Não informada"
        except: 
            area = "Não informada"

    return {
        "url": driver.current_url,
        "aluguel": valor_aluguel,
        "area": area,
        "taxas": taxas,
        "endereco": safe_get_text_css("#map-section > div.section-location-property.section-location-property-classified > h4"),
        "informacao": safe_get_text_css("#article-container hgroup h1")
    }

# --- CONFIGURAÇÃO DO ARQUIVO CSV ---
file_exists = os.path.exists(CSV_FILE)
csv_file = open(CSV_FILE, "a", newline="", encoding="utf-8")
fieldnames = ["url", "aluguel", "area", "taxas", "endereco", "informacao", "data_coleta"]
writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
if not file_exists:
    writer.writeheader()

# --- LOOP PRINCIPAL RECUPERADO E PROTEGIDO ---
BASE_URL_TEMPLATE = "https://www.imovelweb.com.br/terrenos-comerciais-aluguel-rio-de-janeiro-rio-grande-do-sul-santa-catarina-parana-mato-grosso-mato-grosso-do-sul-goias-bahia-ceara-pernambuco-tocantins-paraiba-sergipe-alagoas-piaui-rio-grande-do-norte-maranhao-espirito-santo-minas-gerais-mais-1000-m2-pagina-{}.html"

start_page = load_checkpoint()
scraping_finished = False

while start_page <= MAX_PAGES_TO_SCRAPE and not scraping_finished:
    driver = initialize_driver(load_cookies=True)
    wait = WebDriverWait(driver, 15)
    batch_end_page = min(start_page + PAGES_PER_BATCH, MAX_PAGES_TO_SCRAPE + 1)
    
    imovel_links = set()

    for page_num in range(start_page, batch_end_page):
        current_url = BASE_URL_TEMPLATE.format(page_num)
        print(f"\n--- Coletando Links da Página {page_num} ---")
        retries = 3

        while retries > 0:
            try:
                driver.get(current_url)
                handle_popups(driver)
                save_checkpoint(page_num)

                # Monitoramento ativo contra barreiras Cloudflare na paginação
                html_atual = driver.page_source.lower()
                if "captcha" in html_atual or "challenged" in html_atual or "cloudflare" in html_atual:
                    print("⚠️ Bloqueio temporário identificado. Aguardando descompressão de 45s...")
                    time.sleep(45)
                    driver.refresh()
                    time.sleep(3)

                cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, CARD_SELECTOR)))
                
                # Extração sequencial protegida contra StaleElementReferenceException
                page_links = set()
                for c in cards:
                    try:
                        href = c.get_attribute("href")
                        if href: 
                            page_links.add(href)
                    except (StaleElementReferenceException, NoSuchElementException):
                        continue
                
                if not page_links: 
                    raise TimeoutException()
                
                print(f"{len(page_links)} links encontrados nesta página.")
                imovel_links.update(page_links)
                break 
            except (TimeoutException, StaleElementReferenceException):
                retries -= 1
                print(f"Falha ao carregar listagem mestre. Tentativas restantes: {retries}")
                time.sleep(random.uniform(6, 12))

    # Processamento profundo estável
    if imovel_links:
        print(f"\nNavegando de forma profunda em {len(imovel_links)} imóveis coletados...")
        for link in tqdm(imovel_links, desc="Processando imóveis internos", leave=False):
            try:
                driver.get(link)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#article-container, .price-container-property")))
                
                dados = extrair_dados_imovel(driver)
                dados['data_coleta'] = time.strftime("%Y-%m-%d")
                
                if any(value for key, value in dados.items() if key != 'url'):
                    writer.writerow(dados)
                    csv_file.flush()
                
                time.sleep(random.uniform(2.0, 4.5))
            except Exception:
                continue

    # Preservação segura de sessão e destruição controlada do processo ghost do Windows
    try:
        with open(COOKIE_FILE, "wb") as f: 
            pickle.dump(driver.get_cookies(), f)
    except: 
        pass
    
    driver.quit()
    driver = None  # Evita o erro [WinError 6] no método __del__ do undetected_chromedriver
    
    start_page = batch_end_page 

    if start_page > MAX_PAGES_TO_SCRAPE:
        scraping_finished = True

    if not scraping_finished:
        pause = random.uniform(15, 30)
        print(f"Pausa tática de {pause:.1f}s antes do próximo lote...")
        time.sleep(pause)

csv_file.close()
if os.path.exists(CHECKPOINT_FILE): 
    os.remove(CHECKPOINT_FILE)
print(f"\n🏁 Processamento concluído. Base salva em '{CSV_FILE}'")
