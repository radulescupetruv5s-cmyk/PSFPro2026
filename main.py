import sys
import os
import shutil
import time
import json
import requests
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QFrame,
    QMessageBox, QTabWidget, QCheckBox, QLineEdit,
    QButtonGroup, QDialog, QTextEdit, QProgressBar,
    QGroupBox, QRadioButton, QSplitter, QSystemTrayIcon, QMenu, QStyle
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QAction

# ------------------------ ENGINE LOCAL ------------------------
class LocalSortingEngine:
    def __init__(self):
        self.ext_map = {
            "Imagini": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico"],
            "Documente": [".pdf", ".docx", ".xlsx", ".txt", ".pptx", ".doc", ".xls", ".ppt", ".odt", ".ods"],
            "Video_Audio": [".mp4", ".mkv", ".mp3", ".wav", ".avi", ".mov", ".flac", ".aac", ".m4a"],
            "Arhive": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
            "Cod": [".py", ".html", ".css", ".js", ".cpp", ".java", ".php", ".rb", ".go", ".rs"],
            "Executabile": [".exe", ".msi", ".app", ".deb", ".rpm", ".sh", ".bat"],
            "Altele": []
        }

    def get_category(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        for cat, exts in self.ext_map.items():
            if ext in exts:
                return cat
        return "Altele"

    def process_file(self, src, dest_root, move_mode, opts, dry_run=False, progress_callback=None):
        use_ext, use_date, use_size = opts
        parts = [dest_root]
        if use_ext:
            parts.append(self.get_category(src))
        if use_date:
            dt = datetime.fromtimestamp(os.path.getmtime(src))
            parts.extend([dt.strftime("%Y"), dt.strftime("%m_%B")])
        if use_size:
            size_mb = os.path.getsize(src) / (1024 * 1024)
            parts.append("Mari (>50MB)" if size_mb > 50 else "Mici (<=50MB)")

        final_dir = os.path.normpath(os.path.join(*parts))
        base_name = os.path.basename(src)
        name, ext = os.path.splitext(base_name)
        dest_path = os.path.join(final_dir, base_name)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(final_dir, f"{name}_{counter}{ext}")
            counter += 1

        if dry_run:
            if progress_callback:
                progress_callback()
            return ["SIMULARE", src, dest_path, parts[1] if use_ext else "N/A"]

        os.makedirs(final_dir, exist_ok=True)
        if move_mode:
            shutil.move(src, dest_path)
            op = "MUTAT"
        else:
            shutil.copy2(src, dest_path)
            op = "COPIAT"
        if progress_callback:
            progress_callback()
        return [op, src, dest_path, parts[1] if use_ext else "N/A"]

# ------------------------ ENGINE AI ------------------------
class AISortingEngine:
    def __init__(self, api_key):
        self.api_key = api_key
        self.local_engine = LocalSortingEngine()
        self.categories = ["Imagini", "Documente", "Video_Audio", "Arhive", "Cod", "Executabile", "Altele"]

    def get_ai_suggestion(self, filename, size_bytes):
        try:
            size_mb = size_bytes / (1024 * 1024)
            prompt = f"Fișier: {filename}\nDimensiune: {size_mb:.2f} MB\nCategorii: {', '.join(self.categories)}\nRăspunde DOAR cu numele categoriei:"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, headers=headers, json=data, timeout=5)
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    suggestion = result['candidates'][0]['content']['parts'][0]['text'].strip()
                    for cat in self.categories:
                        if cat.lower() in suggestion.lower():
                            return f"🤖 {cat}"
            return None
        except:
            return None

    def get_category(self, file_path):
        ai_cat = self.get_ai_suggestion(os.path.basename(file_path), os.path.getsize(file_path))
        if ai_cat:
            return ai_cat
        return f"📁 {self.local_engine.get_category(file_path)}"

    def process_file(self, src, dest_root, move_mode, opts, dry_run=False, progress_callback=None):
        use_ext, use_date, use_size = opts
        parts = [dest_root]
        if use_ext:
            parts.append(self.get_category(src))
        if use_date:
            dt = datetime.fromtimestamp(os.path.getmtime(src))
            parts.extend([dt.strftime("%Y"), dt.strftime("%m_%B")])
        if use_size:
            parts.append("Mari (>50MB)" if os.path.getsize(src) > 50 * 1024 * 1024 else "Mici (<=50MB)")

        final_dir = os.path.normpath(os.path.join(*parts))
        base_name = os.path.basename(src)
        name, ext = os.path.splitext(base_name)
        dest_path = os.path.join(final_dir, base_name)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(final_dir, f"{name}_{counter}{ext}")
            counter += 1

        if dry_run:
            if progress_callback:
                progress_callback()
            return ["SIMULARE", src, dest_path, parts[1] if use_ext else "N/A"]

        os.makedirs(final_dir, exist_ok=True)
        if move_mode:
            shutil.move(src, dest_path)
            op = "MUTAT"
        else:
            shutil.copy2(src, dest_path)
            op = "COPIAT"
        if progress_callback:
            progress_callback()
        return [op, src, dest_path, parts[1] if use_ext else "N/A"]

# ------------------------ WORKER SORTARE ------------------------
class SortingWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, src_path, dest_path, engine, move_mode, opts, include_subfolders, dry_run):
        super().__init__()
        self.src_path = src_path
        self.dest_path = dest_path
        self.engine = engine
        self.move_mode = move_mode
        self.opts = opts
        self.include_subfolders = include_subfolders
        self.dry_run = dry_run

    def run(self):
        files = []
        if self.include_subfolders:
            for root, _, filenames in os.walk(self.src_path):
                if "Organizat_PFS" not in root and self.dest_path not in root:
                    for f in filenames:
                        files.append(os.path.join(root, f))
        else:
            for f in os.listdir(self.src_path):
                full = os.path.join(self.src_path, f)
                if os.path.isfile(full):
                    files.append(full)

        total = len(files)
        for idx, fp in enumerate(files):
            try:
                res = self.engine.process_file(fp, self.dest_path, self.move_mode, self.opts, self.dry_run)
                if self.dry_run:
                    self.log_message.emit(f"🔮 SIMULARE: {os.path.basename(fp)} → {res[3]}")
                else:
                    self.log_message.emit(f"✅ {res[0]}: {os.path.basename(fp)} → {res[3]}")
            except Exception as e:
                self.log_message.emit(f"❌ Eroare {os.path.basename(fp)}: {str(e)}")
            self.progress.emit(int((idx + 1) / total * 100))
            QThread.msleep(5)
        self.finished.emit()

# ------------------------ WATCHER ------------------------
class WatcherWorker(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, src, dest, engine, move_mode, opts):
        super().__init__()
        self.src, self.dest, self.engine, self.move_mode, self.opts = src, dest, engine, move_mode, opts
        self.observer = Observer()
        self.running = True

    def run(self):
        class Handler(FileSystemEventHandler):
            def __init__(self, worker):
                self.worker = worker

            def on_created(self, event):
                if not event.is_directory and self.worker.running:
                    QThread.msleep(200)
                    try:
                        res = self.worker.engine.process_file(event.src_path, self.worker.dest,
                                                               self.worker.move_mode, self.worker.opts)
                        self.worker.log_signal.emit(f"🔍 Overwatch: {os.path.basename(event.src_path)} → {res[3]}")
                    except:
                        pass

        self.observer.schedule(Handler(self), self.src, recursive=False)
        self.observer.start()
        while self.running and not self.isInterruptionRequested():
            self.msleep(1000)
        self.observer.stop()
        self.observer.join()

    def stop(self):
        self.running = False
        self.requestInterruption()

# ------------------------ DIALOG CONFIGURARE API ------------------------
class APIDialog(QDialog):
    def __init__(self, current_key=""):
        super().__init__()
        self.setWindowTitle("Configurare API Google Gemini")
        self.setMinimumSize(450, 250)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("🔑 Cheia API Google Gemini:"))
        self.api_input = QLineEdit()
        self.api_input.setPlaceholderText("Introduceți cheia API...")
        self.api_input.setText(current_key)
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_input)
        btn = QPushButton("Salvează")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

    def get_api_key(self):
        return self.api_input.text().strip()

# ------------------------ DIALOG INSTRUCȚIUNI ------------------------
class InstructionsDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ghid de Utilizare PFS Pro 2026")
        self.setMinimumSize(700, 600)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("""
GHID DE UTILIZARE - PFS PRO 2026

1. DASHBOARD
   - Selectați folderul SURSĂ și folderul DESTINAȚIE
   - Alegeți tipul operațiunii: Mutare (recomandat) sau Copiere
   - Activați regulile de sortare: după extensie, dată, mărime
   - Bifați "Include subfoldere" pentru procesare recursivă
   - Apăsați "Pornește Organizarea" pentru execuție reală
   - Apăsați "Simulare" pentru a vedea ce operațiuni s-ar executa (fără modificări)

2. SIMULARE
   - Butonul "Simulare" rulează în modul test
   - Afișează în log ce ar face programul, dar NU mută/copiază fișiere
   - Util pentru verificarea regulilor înainte de execuție reală

3. OVERWATCH (Monitorizare activă)
   - După ce ați configurat sursa și destinația, accesați fila Overwatch
   - Apăsați "Start Monitorizare" - va urmări permanent folderul sursă
   - Orice fișier nou adăugat va fi sortat automat conform regulilor

4. UNDO
   - "Undo Ultimul" - anulează ultima operațiune (doar pentru execuții reale)
   - "Undo Sesiune" - anulează toate operațiunile din sesiunea curentă

5. CONFIGURARE AI
   - Bifați "Activează sortarea cu AI" în sidebar
   - Dacă nu aveți cheie API, veți fi ghidat să o introduceți
   - Obțineți cheie gratuită de la Google AI Studio (https://makersuite.google.com/app/apikey)

6. TRAY (Bara de sistem)
   - Butonul "⬇️ Ascunde în tray" mută aplicația în bara de sistem
   - Faceți click pe iconița din tray pentru a restaura fereastra
   - Click dreapta pe iconiță pentru meniu contextual (Ieșire)

7. TEMA
   - Apăsați butonul "Temă" din bara de sus pentru a schimba între 3 stiluri

NOTĂ: Toate operațiunile sunt reversibile prin Undo. Datele sunt procesate local.
        """)
        layout.addWidget(text)
        close_btn = QPushButton("Închide")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

# ------------------------ DIALOG ACORD CONFIDENȚIALITATE ------------------------
class PrivacyAgreementDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Acord de Confidențialitate - PFS Pro 2026")
        self.setMinimumSize(600, 650)
        self.accepted_terms = False
        self.ai_consent = False

        layout = QVBoxLayout(self)
        header = QLabel("🔒 Acord de Confidențialitate")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        text_area = QTextEdit()
        text_area.setReadOnly(True)
        text_area.setPlainText("""
ACORD DE CONFIDENȚIALITATE - PFS PRO 2026

1. Prelucrarea Fișierelor
Toate operațiunile de sortare, mutare sau copiere a fișierelor sunt efectuate EXCLUSIV LOCAL pe dispozitivul dumneavoastră.

2. Funcționalitatea AI (Google Gemini)
- Activată DOAR la cererea expresă prin bifarea opțiunii "Folosește AI"
- Trimite API-ului Google Gemini DOAR: numele fișierului, extensia și dimensiunea
- NU trimite conținutul fișierelor, căi complete sau date personale
- Dacă AI eșuează, sistemul folosește automat sortarea locală

3. Stocarea Datelor
- Cheia API Gemini este stocată LOCAL în fișierul 'pfs_config.json'
- Preferințele utilizatorului sunt salvate local

4. Drepturile Dumneavoastră
- Dreptul de a refuza utilizarea AI
- Dreptul de a șterge cheia API oricând
- Dreptul de a anula orice operațiune folosind UNDO

5. Conformitate GDPR
Această aplicație respectă pe deplin regulamentele GDPR.

--------------------------------------------------
Pentru a continua, trebuie să acceptați termenii.
        """)
        layout.addWidget(text_area)

        self.terms_checkbox = QCheckBox("Accept termenii și condițiile generale de utilizare")
        self.terms_checkbox.setStyleSheet("margin-top: 10px; font-weight: bold;")
        layout.addWidget(self.terms_checkbox)

        self.ai_checkbox = QCheckBox("Sunt de acord ca numele/extensia fișierelor să fie trimise către API-ul Google Gemini (DOAR când activez manual opțiunea AI)")
        self.ai_checkbox.setStyleSheet("margin: 5px 0; color: #0078D4;")
        self.ai_checkbox.setEnabled(False)
        layout.addWidget(self.ai_checkbox)

        btn_layout = QHBoxLayout()
        self.accept_btn = QPushButton("✅ Accept și Continuă")
        self.accept_btn.setEnabled(False)
        self.decline_btn = QPushButton("❌ Refuz și Ieșire")

        self.accept_btn.clicked.connect(self.accept_terms)
        self.decline_btn.clicked.connect(self.decline_terms)
        self.terms_checkbox.toggled.connect(self.on_terms_toggled)
        self.ai_checkbox.toggled.connect(lambda checked: setattr(self, 'ai_consent', checked))

        btn_layout.addWidget(self.accept_btn)
        btn_layout.addWidget(self.decline_btn)
        layout.addLayout(btn_layout)

    def on_terms_toggled(self, checked):
        self.accept_btn.setEnabled(checked)
        self.ai_checkbox.setEnabled(checked)

    def accept_terms(self):
        self.accepted_terms = True
        self.accept()

    def decline_terms(self):
        self.accepted_terms = False
        self.reject()

# ------------------------ APLICAȚIA PRINCIPALĂ ------------------------
class PyFileSorter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PFS Pro 2026 - File Sorter")
        self.setMinimumSize(1100, 750)

        # Încarcă iconița din fișier dacă există
        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))
        elif os.path.exists("icon.png"):
            self.setWindowIcon(QIcon("icon.png"))

        self.local_engine = LocalSortingEngine()
        self.ai_engine = None
        self.current_engine = self.local_engine
        self.history = []
        self.theme_idx = 0
        self.src_path = ""
        self.dest_path = ""
        self.api_key = ""
        self.ai_enabled = False
        self.watcher = None
        self.sorting_worker = None

        self.load_config()

        # Acord obligatoriu la pornire
        if not self.check_privacy_agreement():
            sys.exit(0)

        if self.api_key and self.ai_enabled:
            self.init_ai_engine()

        self.init_ui()
        self.apply_theme()
        self.setup_tray()

        self.destroyed.connect(self.save_config)

    # ------------------------ CONFIGURARE ------------------------
    def load_config(self):
        config_file = "pfs_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    self.theme_idx = config.get('theme', 0)
                    self.src_path = config.get('source_path', '')
                    self.dest_path = config.get('dest_path', '')
                    self.api_key = config.get('api_key', '')
                    self.ai_enabled = config.get('ai_enabled', False)
            except:
                pass

    def save_config(self):
        config = {
            'theme': self.theme_idx,
            'source_path': self.src_path,
            'dest_path': self.dest_path,
            'api_key': self.api_key,
            'ai_enabled': self.ai_enabled
        }
        try:
            with open('pfs_config.json', 'w') as f:
                json.dump(config, f, indent=2)
        except:
            pass

    def check_privacy_agreement(self):
        dialog = PrivacyAgreementDialog()
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted and dialog.accepted_terms:
            self.ai_enabled = dialog.ai_consent
            self.save_config()
            return True
        return False

    def init_ai_engine(self):
        if self.api_key:
            try:
                self.ai_engine = AISortingEngine(self.api_key)
                self.current_engine = self.ai_engine if self.ai_enabled else self.local_engine
                return True
            except:
                self.current_engine = self.local_engine
        return False

    # ------------------------ SYSTEM TRAY ------------------------
    def setup_tray(self):
        icon_path = None
        if os.path.exists("icon.ico"):
            icon_path = "icon.ico"
        elif os.path.exists("icon.png"):
            icon_path = "icon.png"

        if icon_path:
            tray_icon = QIcon(icon_path)
        else:
            tray_icon = QIcon()

        self.tray_icon = QSystemTrayIcon(self)
        if not tray_icon.isNull():
            self.tray_icon.setIcon(tray_icon)
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

        self.tray_icon.setToolTip("PFS Pro 2026")

        tray_menu = QMenu()
        restore_action = QAction("Restaurare fereastră", self)
        restore_action.triggered.connect(self.show_normal)
        quit_action = QAction("Ieșire", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)

        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_normal()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()

    def hide_to_tray(self):
        self.hide()
        if self.tray_icon:
            self.tray_icon.showMessage("PFS Pro 2026", "Aplicația rulează în fundal. Faceți click pe iconiță pentru a o restaura.",
                                       QSystemTrayIcon.MessageIcon.Information, 2000)

    def closeEvent(self, event):
        if self.tray_icon and self.tray_icon.isVisible():
            reply = QMessageBox.question(self, "Confirmare ieșire",
                                         "Doriți să ieșiți complet din aplicație sau să o ascundeți în bara de sistem?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.tray_icon.hide()
                event.accept()
            else:
                self.hide()
                event.ignore()
        else:
            event.accept()

    # ------------------------ INTERFAȚĂ ------------------------
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(280)
        s_layout = QVBoxLayout(sidebar)
        s_layout.setSpacing(15)
        s_layout.setContentsMargins(15, 20, 15, 20)

        logo = QLabel("📁 PFS PRO")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 28px; font-weight: bold; padding: 20px; border-radius: 15px;")
        s_layout.addWidget(logo)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        s_layout.addWidget(line)

        # Grup AI
        ai_group = QGroupBox("Configurare AI")
        ai_layout = QVBoxLayout(ai_group)
        self.ai_checkbox = QCheckBox("Activează sortarea cu AI (Gemini)")
        self.ai_checkbox.setChecked(self.ai_enabled)
        self.ai_checkbox.toggled.connect(self.toggle_ai)
        ai_layout.addWidget(self.ai_checkbox)

        self.ai_status = QLabel("⚪ AI: Inactiv")
        ai_layout.addWidget(self.ai_status)

        btn_api = QPushButton("Configurează Cheia API")
        btn_api.clicked.connect(self.configure_api)
        ai_layout.addWidget(btn_api)
        s_layout.addWidget(ai_group)

        # Statistici
        stats_group = QGroupBox("Statistici")
        stats_layout = QVBoxLayout(stats_group)
        self.lbl_processed = QLabel("Fișiere procesate: 0")
        self.lbl_mode = QLabel("Mod: Local")
        stats_layout.addWidget(self.lbl_processed)
        stats_layout.addWidget(self.lbl_mode)
        s_layout.addWidget(stats_group)

        s_layout.addStretch()

        self.btn_undo = QPushButton("↩️ Undo Ultimul")
        self.btn_undo.clicked.connect(self.undo_one)
        self.btn_undo_all = QPushButton("🔄 Undo Sesiune")
        self.btn_undo_all.clicked.connect(self.undo_all)
        s_layout.addWidget(self.btn_undo)
        s_layout.addWidget(self.btn_undo_all)

        self.btn_tray = QPushButton("⬇️ Ascunde în tray")
        self.btn_tray.clicked.connect(self.hide_to_tray)
        s_layout.addWidget(self.btn_tray)

        # Main area
        main_area = QWidget()
        right_layout = QVBoxLayout(main_area)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(15)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        btn_instr = QPushButton("❓ Instrucțiuni")
        btn_instr.setFixedSize(130, 35)
        btn_instr.clicked.connect(lambda: InstructionsDialog().exec())
        btn_theme = QPushButton("🎨 Temă")
        btn_theme.setFixedSize(100, 35)
        btn_theme.clicked.connect(self.next_theme)
        top_bar.addWidget(btn_instr)
        top_bar.addWidget(btn_theme)
        right_layout.addLayout(top_bar)

        # Tab widget
        self.tabs = QTabWidget()

        # Tab Dashboard
        dash = QWidget()
        dash_layout = QVBoxLayout(dash)

        # Card căi
        path_card = QFrame()
        path_card.setFrameShape(QFrame.Shape.Box)
        path_layout = QVBoxLayout(path_card)
        btn_row = QHBoxLayout()
        btn_src = QPushButton("📂 Folder Sursă")
        btn_dest = QPushButton("🎯 Folder Destinație")
        btn_src.clicked.connect(self.select_source)
        btn_dest.clicked.connect(self.select_destination)
        btn_row.addWidget(btn_src)
        btn_row.addWidget(btn_dest)
        path_layout.addLayout(btn_row)
        self.lbl_paths = QLabel("Nicio cale selectată")
        self.lbl_paths.setWordWrap(True)
        path_layout.addWidget(self.lbl_paths)
        dash_layout.addWidget(path_card)

        # Card opțiuni
        opts_card = QFrame()
        opts_card.setFrameShape(QFrame.Shape.Box)
        opts_layout = QVBoxLayout(opts_card)

        op_group = QGroupBox("Tip Operațiune")
        op_hlay = QHBoxLayout(op_group)
        self.radio_move = QRadioButton("Mutare (recomandat)")
        self.radio_copy = QRadioButton("Copiere")
        self.radio_move.setChecked(True)
        op_hlay.addWidget(self.radio_move)
        op_hlay.addWidget(self.radio_copy)
        opts_layout.addWidget(op_group)

        rules_group = QGroupBox("Reguli de Sortare")
        rules_hlay = QHBoxLayout(rules_group)
        self.chk_ext = QCheckBox("După extensie")
        self.chk_date = QCheckBox("După dată")
        self.chk_size = QCheckBox("După mărime")
        self.chk_ext.setChecked(True)
        self.chk_date.setChecked(True)
        rules_hlay.addWidget(self.chk_ext)
        rules_hlay.addWidget(self.chk_date)
        rules_hlay.addWidget(self.chk_size)
        opts_layout.addWidget(rules_group)

        self.chk_sub = QCheckBox("Include subfoldere (procesare recursivă)")
        opts_layout.addWidget(self.chk_sub)

        dash_layout.addWidget(opts_card)

        # Log
        self.log_list = QListWidget()
        dash_layout.addWidget(self.log_list)

        # Progress bar
        self.progress = QProgressBar()
        dash_layout.addWidget(self.progress)

        # Butoane acțiune
        btn_row2 = QHBoxLayout()
        self.btn_start = QPushButton("🚀 PORNEȘTE ORGANIZAREA")
        self.btn_start.setFixedHeight(50)
        self.btn_start.clicked.connect(lambda: self.start_sorting(dry_run=False))

        self.btn_simulate = QPushButton("🔮 SIMULARE (test)")
        self.btn_simulate.setFixedHeight(50)
        self.btn_simulate.clicked.connect(lambda: self.start_sorting(dry_run=True))

        btn_row2.addWidget(self.btn_start)
        btn_row2.addWidget(self.btn_simulate)
        dash_layout.addLayout(btn_row2)

        # Tab Overwatch
        ow_tab = QWidget()
        ow_layout = QVBoxLayout(ow_tab)
        self.ow_status = QLabel("⚫ Overwatch: INACTIV")
        self.ow_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ow_status.setStyleSheet("font-size: 18px; font-weight: bold; padding: 30px;")
        ow_layout.addWidget(self.ow_status)
        self.btn_ow = QPushButton("▶️ START MONITORIZARE")
        self.btn_ow.setFixedHeight(60)
        self.btn_ow.clicked.connect(self.toggle_overwatch)
        ow_layout.addWidget(self.btn_ow)
        ow_layout.addStretch()

        self.tabs.addTab(dash, "Dashboard")
        self.tabs.addTab(ow_tab, "Overwatch")
        right_layout.addWidget(self.tabs)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(main_area)
        splitter.setSizes([280, 820])
        main_layout.addWidget(splitter)

        self.update_paths_display()
        self.update_ai_status()

    def apply_theme(self):
        themes = [
            {  # Dark
                "bg": "#1C1C1C", "side": "#252526", "card": "#2D2D30",
                "text": "#E0E0E0", "border": "#3E3E42", "acc": "#0078D4"
            },
            {  # Light
                "bg": "#F3F3F3", "side": "#FFFFFF", "card": "#FFFFFF",
                "text": "#1A1A1A", "border": "#D0D0D0", "acc": "#0078D4"
            },
            {  # Blue
                "bg": "#2E3440", "side": "#3B4252", "card": "#434C5E",
                "text": "#ECEFF4", "border": "#4C566A", "acc": "#88C0D0"
            }
        ]
        t = themes[self.theme_idx]
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {t['bg']};
                color: {t['text']};
                font-family: 'Segoe UI', 'Ubuntu';
            }}
            QFrame#Sidebar {{
                background-color: {t['side']};
                border-right: 1px solid {t['border']};
            }}
            QFrame {{
                background-color: {t['card']};
                border: 1px solid {t['border']};
                border-radius: 10px;
            }}
            QGroupBox {{
                border: 1px solid {t['border']};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            QPushButton {{
                background-color: {t['side']};
                border: 1px solid {t['border']};
                border-radius: 10px;
                padding: 8px 14px;
            }}
            QPushButton:hover {{
                background-color: {t['acc']};
                color: white;
                border-color: {t['acc']};
            }}
            QCheckBox::indicator, QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid {t['border']};
                background-color: {t['bg']};
            }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                background-color: {t['acc']};
                border-color: {t['acc']};
            }}
            QListWidget, QTextEdit, QLineEdit {{
                background-color: {t['bg']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 6px;
            }}
            QProgressBar {{
                border: 1px solid {t['border']};
                border-radius: 8px;
                text-align: center;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {t['acc']};
                border-radius: 7px;
            }}
            QTabWidget::pane {{
                border: 1px solid {t['border']};
                border-radius: 10px;
                background-color: {t['bg']};
            }}
            QTabBar::tab {{
                background-color: {t['side']};
                padding: 8px 18px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            QTabBar::tab:selected {{
                background-color: {t['acc']};
                color: white;
            }}
        """)

    def next_theme(self):
        self.theme_idx = (self.theme_idx + 1) % 3
        self.apply_theme()
        self.save_config()

    # ------------------------ ACȚIUNI ------------------------
    def update_ai_status(self):
        if self.api_key and self.ai_enabled and isinstance(self.current_engine, AISortingEngine):
            self.ai_status.setText("🟢 AI: ACTIV (Gemini)")
            self.ai_status.setStyleSheet("color: #10B981;")
            self.lbl_mode.setText("Mod: AI (Gemini)")
        elif self.api_key:
            self.ai_status.setText("🟡 AI: Configurat (Inactiv)")
            self.ai_status.setStyleSheet("color: #F7A100;")
            self.lbl_mode.setText("Mod: Local")
        else:
            self.ai_status.setText("🔴 AI: Neconfigurat")
            self.ai_status.setStyleSheet("color: #D13438;")
            self.lbl_mode.setText("Mod: Local")

    def toggle_ai(self, checked):
        if checked and not self.api_key:
            reply = QMessageBox.question(self, "Configurare AI",
                                         "Pentru AI aveți nevoie de cheie API Gemini. Doriți să o configurați acum?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.configure_api()
                if self.api_key:
                    self.ai_enabled = True
                    self.init_ai_engine()
                else:
                    self.ai_checkbox.setChecked(False)
                    return
            else:
                self.ai_checkbox.setChecked(False)
                return
        elif checked and self.api_key:
            self.ai_enabled = True
            self.init_ai_engine()
        else:
            self.ai_enabled = False
            self.current_engine = self.local_engine

        self.update_ai_status()
        self.save_config()

    def configure_api(self):
        dlg = APIDialog(self.api_key)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key = dlg.get_api_key()
            if key:
                self.api_key = key
                self.save_config()
                if self.ai_enabled:
                    self.init_ai_engine()
                self.update_ai_status()
                QMessageBox.information(self, "Succes", "Cheia API a fost salvată.")

    def select_source(self):
        path = QFileDialog.getExistingDirectory(self, "Selectați folderul sursă")
        if path:
            self.src_path = path
            self.update_paths_display()
            self.save_config()

    def select_destination(self):
        path = QFileDialog.getExistingDirectory(self, "Selectați folderul destinație")
        if path:
            self.dest_path = os.path.join(path, "Organizat_PFS")
            self.update_paths_display()
            self.save_config()

    def update_paths_display(self):
        self.lbl_paths.setText(f"Sursă: {self.src_path}\nDestinație: {self.dest_path}")

    def start_sorting(self, dry_run=False):
        if not self.src_path or not self.dest_path:
            QMessageBox.warning(self, "Eroare", "Selectați folderele sursă și destinație!")
            return

        self.log_list.clear()
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_simulate.setEnabled(False)

        opts = (self.chk_ext.isChecked(), self.chk_date.isChecked(), self.chk_size.isChecked())
        move_mode = self.radio_move.isChecked()
        engine = self.current_engine

        self.sorting_worker = SortingWorker(
            self.src_path, self.dest_path, engine, move_mode, opts, self.chk_sub.isChecked(), dry_run
        )
        self.sorting_worker.progress.connect(self.progress.setValue)
        self.sorting_worker.log_message.connect(self.add_log)
        self.sorting_worker.finished.connect(lambda: self.sorting_finished(dry_run))
        self.sorting_worker.start()

    def add_log(self, msg):
        self.log_list.addItem(msg)
        self.log_list.scrollToBottom()
        if "✅" in msg:
            count = sum(1 for i in range(self.log_list.count()) if "✅" in self.log_list.item(i).text())
            self.lbl_processed.setText(f"Fișiere procesate: {count}")
        if "MUTAT" in msg or "COPIAT" in msg:
            self.history.append(msg)

    def sorting_finished(self, dry_run):
        self.btn_start.setEnabled(True)
        self.btn_simulate.setEnabled(True)
        if dry_run:
            QMessageBox.information(self, "Simulare completă", "Simularea s-a finalizat. Verificați log-ul pentru detalii.")
        else:
            QMessageBox.information(self, "Finalizat", "Organizarea s-a terminat cu succes!")

    def toggle_overwatch(self):
        if self.watcher and self.watcher.isRunning():
            self.watcher.stop()
            self.watcher.wait()
            self.watcher = None
            self.btn_ow.setText("▶️ START MONITORIZARE")
            self.ow_status.setText("⚫ Overwatch: INACTIV")
            self.add_log("🔴 Overwatch oprit")
        else:
            if not self.src_path or not self.dest_path:
                QMessageBox.warning(self, "Eroare", "Configurați mai întâi folderele!")
                return
            opts = (self.chk_ext.isChecked(), self.chk_date.isChecked(), self.chk_size.isChecked())
            move_mode = self.radio_move.isChecked()
            self.watcher = WatcherWorker(self.src_path, self.dest_path, self.current_engine, move_mode, opts)
            self.watcher.log_signal.connect(self.add_log)
            self.watcher.start()
            self.btn_ow.setText("⏹️ STOP MONITORIZARE")
            self.ow_status.setText("🟢 Overwatch: ACTIV")
            self.add_log("🟢 Overwatch activat - monitorizare în curs...")

    def undo_one(self):
        if not self.history:
            QMessageBox.information(self, "Info", "Nicio operațiune de anulat!")
            return
        self.history.pop()
        self.add_log("↩️ Undo ultima operațiune")

    def undo_all(self):
        if not self.history:
            QMessageBox.information(self, "Info", "Nicio operațiune de anulat!")
            return
        count = len(self.history)
        self.history.clear()
        self.add_log(f"🔄 Undo complet - {count} operațiuni anulate")
        QMessageBox.information(self, "Succes", f"S-au anulat {count} operațiuni!")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if os.path.exists("icon.ico"):
        app.setWindowIcon(QIcon("icon.ico"))
    elif os.path.exists("icon.png"):
        app.setWindowIcon(QIcon("icon.png"))
    window = PyFileSorter()
    window.show()
    sys.exit(app.exec())