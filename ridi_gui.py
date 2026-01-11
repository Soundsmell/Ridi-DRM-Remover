import os
os.environ["QT_API"] = "pyside6"
import sys
import json
import webbrowser
import urllib.parse
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QTableWidgetItem, QHeaderView, QLabel, QFrame
from qfluentwidgets import (FluentWindow, SubtitleLabel, PrimaryPushButton, LineEdit, 
                            TableWidget, MessageBox, PushButton, InfoBar, InfoBarPosition,
                            NavigationItemPosition, FluentIcon as FIF, CardWidget, BodyLabel,
                            setTheme, Theme, StrongBodyLabel, CaptionLabel, TransparentToolButton,
                            setThemeColor)

# 기존 로직 import
import ridi_utils
from ridi import ConfigManager, RIDI_LOGIN_URL, RIDI_USER_DEVICES_API

# Worker Thread for Exporting (UI 끊김 방지)
class ExportThread(QThread):
    progress = Signal(str)
    finished_one = Signal(bool)
    
    def __init__(self, books, device_id, output_dir):
        super().__init__()
        self.books = books
        self.device_id = device_id
        self.output_dir = output_dir
        self.is_running = True

    def run(self):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(self.output_dir)
            for book in self.books:
                if not self.is_running: break
                self.progress.emit(f"Exporting: {book.id}...")
                try:
                    # ridi_utils.decrypt_with_progress 사용 (로깅은 제외)
                    key = ridi_utils.decrypt_key(book, self.device_id)
                    data = ridi_utils.decrypt_book(book, key)
                    
                    title = ridi_utils.extract_title(book.format, data) or book.id
                    safe_title = ridi_utils._sanitize_filename(title)
                    filename = f"{safe_title}.{book.format.extension()}"
                    
                    Path(filename).write_bytes(data)
                    self.finished_one.emit(True)
                except Exception as e:
                    self.progress.emit(f"Error {book.id}: {e}")
                    self.finished_one.emit(False)
        finally:
            os.chdir(original_cwd)

class AuthInterface(QWidget):
    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent=parent)
        self.config_mgr = config_mgr
        
        # 메인 레이아웃 (여백 최소화)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(8)
        
        # 1. 타이틀 영역
        self.main_layout.addWidget(SubtitleLabel("계정 연동", self))
        
        # 2. 로그인 섹션
        login_card = CardWidget(self)
        login_layout = QVBoxLayout(login_card)
        login_layout.setContentsMargins(12, 10, 12, 10)
        
        # 설명 + 버튼 가로 배치
        l_row = QHBoxLayout()
        l_desc = QVBoxLayout()
        l_desc.setSpacing(2)
        l_desc.addWidget(StrongBodyLabel("1. 로그인", self))
        l_desc.addWidget(CaptionLabel("브라우저에서 리디북스에 로그인 후 JSON을 복사하세요.", self))
        l_row.addLayout(l_desc)
        l_row.addStretch(1)
        
        self.login_btn = PushButton("브라우저 열기", self, FIF.LINK)
        self.login_btn.clicked.connect(self.open_browser)
        l_row.addWidget(self.login_btn)
        
        login_layout.addLayout(l_row)
        self.main_layout.addWidget(login_card)

        # 3. 등록 섹션
        reg_card = CardWidget(self)
        reg_layout = QVBoxLayout(reg_card)
        reg_layout.setContentsMargins(12, 10, 12, 10)
        
        # 설명
        reg_layout.addWidget(StrongBodyLabel("2. 기기 등록", self))
        
        # 입력창 + 버튼
        input_row = QHBoxLayout()
        self.json_input = LineEdit(self)
        self.json_input.setPlaceholderText("JSON 붙여넣기")
        self.json_input.setClearButtonEnabled(True)
        input_row.addWidget(self.json_input)
        
        self.register_btn = PrimaryPushButton("등록", self, FIF.ADD)
        self.register_btn.setFixedWidth(80)
        self.register_btn.clicked.connect(self.process_json)
        input_row.addWidget(self.register_btn)
        
        reg_layout.addLayout(input_row)
        self.main_layout.addWidget(reg_card)
        
        self.main_layout.addStretch(1)

    def open_browser(self):
        callback_url = RIDI_USER_DEVICES_API
        state_payload = json.dumps({"return_url": callback_url}, separators=(',', ':'))
        target_url = f"{RIDI_LOGIN_URL}?state={urllib.parse.quote(state_payload)}"
        webbrowser.open(target_url)

    def process_json(self):
        text = self.json_input.text().strip()
        if not text:
            self.show_error("JSON 텍스트를 입력해주세요.")
            return

        try:
            if not text.startswith("{"):
                start = text.find("{")
                if start != -1: text = text[start:]
            
            data = json.loads(text)
            devices = data.get("user_devices", [])
            
            if not devices:
                self.show_error("유효한 기기 정보가 없습니다.")
                return

            target = devices[0] 
            
            user_idx = target.get("user_idx")
            device_id = target.get("device_id")
            device_name = target.get("device_nick")
            
            if user_idx and device_id:
                self.config_mgr.add_user(user_idx, device_id, device_name, {})
                InfoBar.success(
                    title='완료',
                    content=f"{user_idx} ({device_name}) 기기가 등록되었습니다.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    parent=self.window()
                )
                self.json_input.clear()
            else:
                self.show_error("기기 정보가 불완전합니다.")

        except Exception as e:
            self.show_error(f"오류 발생: {e}")

    def show_error(self, msg):
        InfoBar.error(title='오류', content=msg, orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP, parent=self.window())


class LibraryInterface(QWidget):
    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent=parent)
        self.config_mgr = config_mgr
        self.books = []
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(8)
        
        # Header (Title + Controls)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(SubtitleLabel("내 서재", self))
        self.status_label = CaptionLabel("준비됨", self)
        title_box.addWidget(self.status_label)
        header_layout.addLayout(title_box)
        
        header_layout.addStretch(1)
        
        self.refresh_btn = TransparentToolButton(FIF.SYNC, self)
        self.refresh_btn.setToolTip("목록 새로고침")
        self.refresh_btn.clicked.connect(self.load_books)
        header_layout.addWidget(self.refresh_btn)
        
        self.export_btn = PrimaryPushButton("내보내기", self, FIF.DOWNLOAD)
        self.export_btn.clicked.connect(self.export_selected)
        header_layout.addWidget(self.export_btn)
        
        self.main_layout.addLayout(header_layout)
        
        # Table
        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['ID', 'Format', 'Path'])
        # 컬럼 너비 꽉 차게 설정
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        
        self.main_layout.addWidget(self.table)

    def load_books(self):
        active = self.config_mgr.get_active_user()
        if not active:
            self.status_label.setText("로그인이 필요합니다.")
            return
            
        try:
            lib_path = ridi_utils.library_path(active["user_idx"])
            if not lib_path.exists():
                self.status_label.setText("리디북스 폴더를 찾을 수 없습니다.")
                return

            all_infos = ridi_utils.book_infos(lib_path)
            self.books = [b for b in all_infos if b.file_path(ridi_utils.FileKind.DATA).exists()]
            
            self.table.setRowCount(len(self.books))
            for i, book in enumerate(self.books):
                # ID
                self.table.setItem(i, 0, QTableWidgetItem(book.id))
                # Format (Icon + Text could be better but Text for now)
                self.table.setItem(i, 1, QTableWidgetItem(book.format.extension().upper()))
                # Path
                path_item = QTableWidgetItem(str(book.path))
                path_item.setToolTip(str(book.path))
                self.table.setItem(i, 2, path_item)
                
            self.status_label.setText(f"{len(self.books)}권을 불러왔습니다.")
            
        except Exception as e:
            self.status_label.setText(f"로드 오류: {e}")

    def export_selected(self):
        indexes = self.table.selectedIndexes()
        rows = sorted(set(index.row() for index in indexes))
        
        if not rows:
            # 전체 내보내기?
            w = MessageBox("내보내기", "선택된 책이 없습니다. 전체를 내보내시겠습니까?", self.window())
            if w.exec():
                selected_books = self.books
            else:
                return
        else:
            selected_books = [self.books[r] for r in rows]

        active = self.config_mgr.get_active_user()
        if not active: return
        
        folder = QFileDialog.getExistingDirectory(self, "저장할 폴더 선택")
        if not folder: return
        
        self.export_btn.setDisabled(True)
        self.status_label.setText("내보내기 진행 중...")
        
        self.worker = ExportThread(selected_books, active["device_id"], folder)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_export_finished)
        self.worker.start()

    def on_export_finished(self):
        self.export_btn.setDisabled(False)
        self.status_label.setText("작업 완료")
        InfoBar.success("완료", "내보내기가 끝났습니다.", parent=self.window())


class RidiWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ridi DRM Remover (GUI)")
        # 창 크기를 작고 고정된 크기(Compact)로 설정
        self.setFixedSize(560, 520)
        
        self.config_mgr = ConfigManager(Path.home() / ".ridi_auth.json")
        
        self.library_interface = LibraryInterface(self.config_mgr, self)
        self.library_interface.setObjectName("libraryInterface")
        self.auth_interface = AuthInterface(self.config_mgr, self)
        self.auth_interface.setObjectName("authInterface")
        
        self.addSubInterface(self.library_interface, FIF.BOOK_SHELF, "내 서재")
        self.addSubInterface(self.auth_interface, FIF.PEOPLE, "계정 관리")
        
        self.library_interface.load_books()

if __name__ == "__main__":
    # [설정 변경] 아이콘과 UI를 더 부드럽게(Smooth) 처리하기 위해 'PassThrough' 정책으로 변경
    # 픽셀을 강제로 맞추지 않고 소수점 단위로 부드럽게 렌더링합니다. (안티에일리어싱 효과 극대화)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    
    app = QApplication(sys.argv)
    
    # 다크 모드 적용
    setTheme(Theme.DARK)
    
    # 리디북스 브랜드 포인트 컬러 적용 (RIDI Blue)
    setThemeColor("#0077D9")

    # 폰트 파일 로드
    target_font_family = "Segoe UI"
        
    # 전역 스타일시트: 폰트 강제 적용
    app.setStyleSheet(f"""
                    * {{
                        font-family: '{target_font_family}', 'Malgun Gothic';
                    }}
                    """)
    
    w = RidiWindow()
    w.show()
    sys.exit(app.exec())
