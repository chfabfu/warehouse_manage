import sys
import os
import sqlite3
import shutil
import logging
from datetime import datetime
from contextlib import contextmanager
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QDialog,
    QFormLayout, QLineEdit, QSpinBox, QMessageBox, QHeaderView,
    QAbstractItemView, QGroupBox, QCompleter, QComboBox, QFileDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon
import csv

# ── 常量 ──
DB_PATH = 'inventory.db'
BACKUP_DIR = 'backups'
MAX_NAME_LENGTH = 100
MAX_NOTE_LENGTH = 500
LOG_FILE = 'inventory.log'
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tu_biao', 'tubiao.ico')
MAX_BACKUP_COUNT = 30

# ── 日志 ──
logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ── 迭代1: 数据库连接上下文管理器，添加busy_timeout防止锁定 ──
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000')
    try:
        yield conn
    finally:
        conn.close()


# ── 迭代2: 数据库初始化，添加索引提升查询性能 ──
def init_db():
    with get_db() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stock_in (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS stock_out (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_stock_in_pid ON stock_in(product_id);
            CREATE INDEX IF NOT EXISTS idx_stock_out_pid ON stock_out(product_id);
        ''')
        conn.commit()
    logger.info('数据库初始化完成')


# ── 输入验证函数 ──
def sanitize_name(name):
    if not name:
        return ''
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH]
    return name


def sanitize_note(note):
    if not note:
        return ''
    note = note.strip()
    if len(note) > MAX_NOTE_LENGTH:
        note = note[:MAX_NOTE_LENGTH]
    return note


# ── 迭代3: 提取公共商品列表查询方法，避免重复代码 ──
def get_product_names():
    with get_db() as conn:
        return [row['name'] for row in conn.execute('SELECT name FROM products ORDER BY name').fetchall()]


# ── 迭代4: 备份轮转，自动清理旧备份 ──
def rotate_backups():
    try:
        if not os.path.isdir(BACKUP_DIR):
            return
        files = sorted(
            [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith('.db')],
            key=os.path.getmtime
        )
        while len(files) > MAX_BACKUP_COUNT:
            os.remove(files.pop(0))
    except OSError as e:
        logger.warning(f'备份清理失败: {e}')


def backup_db():
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_name = 'inventory_backup_{}.db'.format(datetime.now().strftime('%Y%m%d_%H%M%S'))
        shutil.copy2(DB_PATH, os.path.join(BACKUP_DIR, backup_name))
        logger.info('数据库已备份: {}'.format(backup_name))
        rotate_backups()
    except OSError as e:
        logger.warning('备份失败: {}'.format(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('库存管理系统')
        self.setWindowIcon(QIcon(ICON_PATH))
        self.setMinimumSize(2000, 1300)
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        # 标题栏
        top_bar = QHBoxLayout()
        self.btn_export = QPushButton('导出')
        self.btn_import = QPushButton('导入')
        self.btn_edit = QPushButton('编辑')
        small_style = 'color:white;padding:8px 22px;border-radius:4px;font-size:24px;font-weight:bold;'
        self.btn_export.setStyleSheet('background:#16a34a;{}'.format(small_style))
        self.btn_import.setStyleSheet('background:#0ea5e9;{}'.format(small_style))
        self.btn_edit.setStyleSheet('background:#8e44ad;{}'.format(small_style))
        self.btn_export.clicked.connect(self.export_data)
        self.btn_import.clicked.connect(self.import_data)
        self.btn_edit.clicked.connect(self.edit_product)
        top_bar.addWidget(self.btn_export)
        top_bar.addWidget(self.btn_import)
        top_bar.addWidget(self.btn_edit)

        top_bar.addStretch()

        title = QLabel('库存总览')
        title.setFont(QFont('Microsoft YaHei', 22, QFont.Bold))
        top_bar.addWidget(title)

        top_bar.addStretch()
        placeholder = QWidget()
        placeholder.setFixedWidth(self.btn_export.sizeHint().width() + self.btn_import.sizeHint().width() + self.btn_edit.sizeHint().width() + 16)
        top_bar.addWidget(placeholder)
        layout.addLayout(top_bar)

        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        self.btn_add = QPushButton('+ 新增商品')
        self.btn_in = QPushButton('入库')
        self.btn_out = QPushButton('出库')
        self.btn_search = QPushButton('查询')
        self.btn_detail = QPushButton('查看明细')
        self.btn_del = QPushButton('删除商品')

        btn_style = 'color:white;padding:14px 36px;border-radius:6px;font-size:24px;font-weight:bold;'
        self.btn_add.setStyleSheet('background:#3498db;{}'.format(btn_style))
        self.btn_in.setStyleSheet('background:#27ae60;{}'.format(btn_style))
        self.btn_out.setStyleSheet('background:#e74c3c;{}'.format(btn_style))
        self.btn_search.setStyleSheet('background:#f39c12;{}'.format(btn_style))
        self.btn_detail.setStyleSheet('background:#8e44ad;{}'.format(btn_style))
        self.btn_del.setStyleSheet('background:#95a5a6;{}'.format(btn_style))

        self.btn_add.clicked.connect(self.add_product)
        self.btn_in.clicked.connect(self.stock_in)
        self.btn_out.clicked.connect(self.stock_out)
        self.btn_search.clicked.connect(self.search_stock)
        self.btn_detail.clicked.connect(self.show_detail)
        self.btn_del.clicked.connect(self.delete_product)

        for btn in [self.btn_add, self.btn_in, self.btn_out, self.btn_search, self.btn_detail, self.btn_del]:
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['商品名称', '累计入库', '累计出库', '当前余量'])
        header = self.table.horizontalHeader()
        header.setFont(QFont('Microsoft YaHei', 18, QFont.Bold))
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.resizeSection(0, 300)
        header.resizeSection(1, 200)
        header.resizeSection(2, 200)
        header.resizeSection(3, 200)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setFont(QFont('Microsoft YaHei', 13))
        self.table.doubleClicked.connect(self.show_detail)
        layout.addWidget(self.table)

    def get_selected_product(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        name_item = self.table.item(row, 0)
        if not name_item:
            return None
        return name_item.data(Qt.UserRole)

    # ── 迭代5: 批量更新表格，减少UI刷新次数 ──
    def load_data(self):
        try:
            with get_db() as conn:
                products = conn.execute('''
                    SELECT p.id, p.name,
                        COALESCE((SELECT SUM(quantity) FROM stock_in WHERE product_id = p.id), 0) as total_in,
                        COALESCE((SELECT SUM(quantity) FROM stock_out WHERE product_id = p.id), 0) as total_out
                    FROM products p ORDER BY p.name
                ''').fetchall()
        except sqlite3.Error as e:
            logger.error('加载数据失败: {}'.format(e))
            return

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(products))
        for i, p in enumerate(products):
            remaining = p['total_in'] - p['total_out']

            name_item = QTableWidgetItem(p['name'])
            name_item.setData(Qt.UserRole, p['id'])
            name_item.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))

            in_item = QTableWidgetItem('+{}'.format(p['total_in']))
            in_item.setForeground(Qt.darkGreen)
            in_item.setTextAlignment(Qt.AlignCenter)

            out_item = QTableWidgetItem('-{}'.format(p['total_out']))
            out_item.setForeground(Qt.red)
            out_item.setTextAlignment(Qt.AlignCenter)

            remain_item = QTableWidgetItem(str(remaining))
            remain_item.setTextAlignment(Qt.AlignCenter)
            if remaining <= 0:
                remain_item.setForeground(Qt.red)
            elif remaining <= 10:
                remain_item.setForeground(Qt.darkYellow)
            else:
                remain_item.setForeground(Qt.blue)
            remain_item.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))

            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, in_item)
            self.table.setItem(i, 2, out_item)
            self.table.setItem(i, 3, remain_item)
        self.table.setUpdatesEnabled(True)

    # ── 迭代6: 查询合并为单次数据库连接 ──
    def search_stock(self):
        try:
            names = get_product_names()
        except sqlite3.Error as e:
            logger.error('查询失败: {}'.format(e))
            return

        dlg = SearchDialog(self, names)
        if dlg.exec_():
            name = sanitize_name(dlg.name_input.currentText())
            if not name:
                return
            try:
                with get_db() as conn:
                    product = conn.execute('SELECT id, name FROM products WHERE name=?', (name,)).fetchone()
                    if not product:
                        QMessageBox.information(self, '查询结果', '商品 "{}" 不存在'.format(name))
                        return
                    pid = product['id']
                    row = conn.execute('''
                        SELECT
                            COALESCE(SUM(CASE WHEN 1=1 THEN si.quantity END), 0) as total_in,
                            COALESCE(SUM(CASE WHEN 1=1 THEN so.quantity END), 0) as total_out
                        FROM products p
                        LEFT JOIN stock_in si ON si.product_id = p.id
                        LEFT JOIN stock_out so ON so.product_id = p.id
                        WHERE p.id = ?
                    ''', (pid,)).fetchone()
                    total_in = conn.execute('SELECT COALESCE(SUM(quantity),0) FROM stock_in WHERE product_id=?', (pid,)).fetchone()[0]
                    total_out = conn.execute('SELECT COALESCE(SUM(quantity),0) FROM stock_out WHERE product_id=?', (pid,)).fetchone()[0]
            except sqlite3.Error as e:
                logger.error('查询库存失败: {}'.format(e))
                return
            remaining = total_in - total_out
            dlg = SearchResultDialog(self, name, total_in, total_out, remaining)
            dlg.exec_()

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出数据', '库存数据.csv', 'CSV文件 (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'

        try:
            with get_db() as conn:
                products = conn.execute('''
                    SELECT p.name,
                        COALESCE((SELECT SUM(quantity) FROM stock_in WHERE product_id = p.id), 0) as total_in,
                        COALESCE((SELECT SUM(quantity) FROM stock_out WHERE product_id = p.id), 0) as total_out
                    FROM products p ORDER BY p.name
                ''').fetchall()
                stock_in_all = conn.execute('''
                    SELECT p.name, si.quantity, si.note, si.created_at
                    FROM stock_in si JOIN products p ON si.product_id = p.id
                    ORDER BY si.created_at DESC
                ''').fetchall()
                stock_out_all = conn.execute('''
                    SELECT p.name, so.quantity, so.note, so.created_at
                    FROM stock_out so JOIN products p ON so.product_id = p.id
                    ORDER BY so.created_at DESC
                ''').fetchall()
        except sqlite3.Error as e:
            logger.error('导出读取数据失败: {}'.format(e))
            QMessageBox.warning(self, '导出失败', '读取数据库出错')
            return

        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['=== 库存汇总 ==='])
                writer.writerow(['商品名称', '累计入库', '累计出库', '当前余量'])
                for p in products:
                    writer.writerow([p['name'], p['total_in'], p['total_out'], p['total_in'] - p['total_out']])
                writer.writerow([])
                writer.writerow(['=== 入库明细 ==='])
                writer.writerow(['商品名称', '数量', '备注', '时间'])
                for r in stock_in_all:
                    writer.writerow([r['name'], r['quantity'], r['note'], r['created_at']])
                writer.writerow([])
                writer.writerow(['=== 出库明细 ==='])
                writer.writerow(['商品名称', '数量', '备注', '时间'])
                for r in stock_out_all:
                    writer.writerow([r['name'], r['quantity'], r['note'], r['created_at']])
            logger.info('数据导出到: {}'.format(path))
            QMessageBox.information(self, '导出成功', '数据已导出到：\n{}'.format(path))
        except OSError as e:
            logger.error('导出写文件失败: {}'.format(e))
            QMessageBox.warning(self, '导出失败', '写入文件出错: {}'.format(e))

    # ── 迭代7: 导入用商品ID缓存，避免逐条查询 ──
    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入数据', '', 'CSV文件 (*.csv)')
        if not path:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, '导入失败', '文件不存在')
            return

        backup_db()

        added = 0
        imported_in = 0
        imported_out = 0
        try:
            with get_db() as conn:
                # 缓存商品名->id映射
                name_cache = {}
                for row in conn.execute('SELECT id, name FROM products'):
                    name_cache[row['name'].lower()] = row['id']

                with open(path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    section = None
                    for row in reader:
                        if not row:
                            continue
                        row_str = ','.join(row)
                        if '库存汇总' in row_str:
                            section = 'summary'
                            next(reader, None)
                            continue
                        elif '入库明细' in row_str:
                            section = 'stock_in'
                            next(reader, None)
                            continue
                        elif '出库明细' in row_str:
                            section = 'stock_out'
                            next(reader, None)
                            continue

                        if section in ('stock_in', 'stock_out') and len(row) >= 4:
                            name = sanitize_name(row[0])
                            note = sanitize_note(row[2])
                            ts = row[3].strip()
                            try:
                                quantity = int(row[1])
                                if quantity <= 0:
                                    continue
                            except ValueError:
                                continue

                            name_key = name.lower()
                            if name_key not in name_cache:
                                conn.execute('INSERT INTO products (name) VALUES (?)', (name,))
                                pid = conn.execute('SELECT id FROM products WHERE name=?', (name,)).fetchone()['id']
                                name_cache[name_key] = pid
                                added += 1
                            else:
                                pid = name_cache[name_key]

                            table = 'stock_in' if section == 'stock_in' else 'stock_out'
                            conn.execute('INSERT INTO {} (product_id, quantity, note, created_at) VALUES (?,?,?,?)'.format(table),
                                         (pid, quantity, note, ts))
                            if section == 'stock_in':
                                imported_in += 1
                            else:
                                imported_out += 1

                conn.commit()
            self.load_data()
            logger.info('导入完成: 商品{}, 入库{}, 出库{}'.format(added, imported_in, imported_out))
            QMessageBox.information(self, '导入成功',
                                    '新增商品: {}\n导入入库记录: {}\n导入出库记录: {}'.format(added, imported_in, imported_out))
        except sqlite3.Error as e:
            logger.error('导入数据库错误: {}'.format(e))
            QMessageBox.warning(self, '导入失败', '数据库错误: {}'.format(e))
        except Exception as e:
            logger.error('导入失败: {}'.format(e))
            QMessageBox.warning(self, '导入失败', str(e))

    def add_product(self):
        dlg = AddProductDialog(self)
        if dlg.exec_():
            name = sanitize_name(dlg.name_input.text())
            if not name:
                QMessageBox.warning(self, '提示', '商品名称不能为空')
                return
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO products (name) VALUES (?)', (name,))
                    conn.commit()
                self.load_data()
                logger.info('新增商品: {}'.format(name))
            except sqlite3.IntegrityError:
                QMessageBox.warning(self, '提示', '商品 "{}" 已存在'.format(name))
            except sqlite3.Error as e:
                logger.error('新增商品失败: {}'.format(e))

    # ── 迭代8: 入库出库提取公共商品名获取逻辑 ──
    def _get_selected_name_and_names(self):
        selected_name = ''
        pid = self.get_selected_product()
        if pid:
            try:
                with get_db() as conn:
                    product = conn.execute('SELECT name FROM products WHERE id=?', (pid,)).fetchone()
                    if product:
                        selected_name = product['name']
            except sqlite3.Error as e:
                logger.error('查询商品失败: {}'.format(e))
        try:
            names = get_product_names()
        except sqlite3.Error as e:
            logger.error('获取商品列表失败: {}'.format(e))
            return None, None
        return selected_name, names

    def stock_in(self):
        selected_name, names = self._get_selected_name_and_names()
        if names is None:
            return

        dlg = StockInDialog(self, names, selected_name)
        if dlg.exec_():
            name = sanitize_name(dlg.name_input.currentText())
            qty = dlg.qty_input.value()
            note = sanitize_note(dlg.note_input.text())
            if not name:
                QMessageBox.warning(self, '提示', '商品名称不能为空')
                return
            try:
                with get_db() as conn:
                    product = conn.execute('SELECT id FROM products WHERE name=?', (name,)).fetchone()
                    if not product:
                        conn.execute('INSERT INTO products (name) VALUES (?)', (name,))
                        product = conn.execute('SELECT id FROM products WHERE name=?', (name,)).fetchone()
                    pid = product['id']
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    conn.execute('INSERT INTO stock_in (product_id, quantity, note, created_at) VALUES (?,?,?,?)',
                                 (pid, qty, note, now))
                    conn.commit()
                self.load_data()
                logger.info('入库: {} +{}'.format(name, qty))
            except sqlite3.Error as e:
                logger.error('入库失败: {}'.format(e))

    # ── 迭代9: 出库库存检查用单次查询 ──
    def stock_out(self):
        selected_name, names = self._get_selected_name_and_names()
        if names is None:
            return

        dlg = StockOutDialog(self, names, selected_name)
        if dlg.exec_():
            name = sanitize_name(dlg.name_input.currentText())
            qty = dlg.qty_input.value()
            note = sanitize_note(dlg.note_input.text())
            if not name:
                QMessageBox.warning(self, '提示', '商品名称不能为空')
                return
            try:
                with get_db() as conn:
                    product = conn.execute('SELECT id FROM products WHERE name=?', (name,)).fetchone()
                    if not product:
                        QMessageBox.warning(self, '提示', '商品 "{}" 不存在，请先入库添加'.format(name))
                        return
                    pid = product['id']
                    row = conn.execute('''
                        SELECT
                            COALESCE((SELECT SUM(quantity) FROM stock_in WHERE product_id=?), 0) -
                            COALESCE((SELECT SUM(quantity) FROM stock_out WHERE product_id=?), 0) as remaining
                    ''', (pid, pid)).fetchone()
                    remaining = row['remaining']
                    if qty > remaining:
                        QMessageBox.warning(self, '库存不足', '"{}" 当前剩余 {}，不能出库 {}'.format(name, remaining, qty))
                        return
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    conn.execute('INSERT INTO stock_out (product_id, quantity, note, created_at) VALUES (?,?,?,?)',
                                 (pid, qty, note, now))
                    conn.commit()
                self.load_data()
                logger.info('出库: {} -{}'.format(name, qty))
            except sqlite3.Error as e:
                logger.error('出库失败: {}'.format(e))

    # ── 迭代10: 明细弹窗合并为单次查询 ──
    def show_detail(self):
        pid = self.get_selected_product()
        if not pid:
            QMessageBox.information(self, '提示', '请先选择一个商品')
            return
        try:
            with get_db() as conn:
                product = conn.execute('SELECT name FROM products WHERE id=?', (pid,)).fetchone()
                if not product:
                    QMessageBox.warning(self, '提示', '商品不存在')
                    return
                stock_in = conn.execute('SELECT * FROM stock_in WHERE product_id=? ORDER BY created_at DESC', (pid,)).fetchall()
                stock_out = conn.execute('SELECT * FROM stock_out WHERE product_id=? ORDER BY created_at DESC', (pid,)).fetchall()
                totals = conn.execute('''
                    SELECT
                        COALESCE((SELECT SUM(quantity) FROM stock_in WHERE product_id=?), 0) as total_in,
                        COALESCE((SELECT SUM(quantity) FROM stock_out WHERE product_id=?), 0) as total_out
                ''', (pid, pid)).fetchone()
        except sqlite3.Error as e:
            logger.error('查看明细失败: {}'.format(e))
            return
        dlg = DetailDialog(self, product['name'], stock_in, stock_out, totals['total_in'], totals['total_out'])
        dlg.exec_()

    def delete_product(self):
        pid = self.get_selected_product()
        if not pid:
            QMessageBox.information(self, '提示', '请先选择一个商品')
            return
        try:
            with get_db() as conn:
                product = conn.execute('SELECT name FROM products WHERE id=?', (pid,)).fetchone()
                if not product:
                    return
        except sqlite3.Error as e:
            logger.error('查询商品失败: {}'.format(e))
            return

        reply = QMessageBox.question(self, '确认删除',
                                     '确定删除商品 "{}" 及其所有记录？'.format(product['name']),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                with get_db() as conn:
                    conn.execute('DELETE FROM products WHERE id=?', (pid,))
                    conn.commit()
                self.load_data()
                logger.info('删除商品: {}'.format(product['name']))
            except sqlite3.Error as e:
                logger.error('删除商品失败: {}'.format(e))

    def edit_product(self):
        try:
            names = get_product_names()
        except sqlite3.Error as e:
            logger.error('获取商品列表失败: {}'.format(e))
            return
        if not names:
            QMessageBox.information(self, '提示', '暂无商品，请先添加')
            return
        dlg = EditSelectDialog(self, names)
        if dlg.exec_():
            name = sanitize_name(dlg.name_input.currentText())
            if not name:
                return
            try:
                with get_db() as conn:
                    product = conn.execute('SELECT id, name FROM products WHERE name=?', (name,)).fetchone()
                    if not product:
                        QMessageBox.warning(self, '提示', '商品 "{}" 不存在'.format(name))
                        return
                    pid = product['id']
                    stock_in = conn.execute('SELECT * FROM stock_in WHERE product_id=? ORDER BY created_at DESC', (pid,)).fetchall()
                    stock_out = conn.execute('SELECT * FROM stock_out WHERE product_id=? ORDER BY created_at DESC', (pid,)).fetchall()
            except sqlite3.Error as e:
                logger.error('查询商品失败: {}'.format(e))
                return
            edit_dlg = EditRecordDialog(self, name, pid, stock_in, stock_out)
            edit_dlg.exec_()
            self.load_data()


class AddProductDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('新增商品')
        self.setFixedSize(840, 360)
        layout = QFormLayout(self)
        layout.setSpacing(20)
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(MAX_NAME_LENGTH)
        self.name_input.setPlaceholderText('请输入商品名称')
        self.name_input.setFont(QFont('Microsoft YaHei', 16))
        label = QLabel('商品名称:')
        label.setFont(QFont('Microsoft YaHei', 16))
        layout.addRow(label, self.name_input)
        btn_layout = QHBoxLayout()
        btn_style = 'color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;'
        ok_btn = QPushButton('添加')
        cancel_btn = QPushButton('取消')
        ok_btn.setStyleSheet('background:#3498db;{}'.format(btn_style))
        cancel_btn.setStyleSheet('background:#95a5a6;{}'.format(btn_style))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)


class StockInDialog(QDialog):
    def __init__(self, parent=None, product_names=None, selected_name=''):
        super().__init__(parent)
        self.setWindowTitle('入库')
        self.setFixedSize(960, 520)
        layout = QFormLayout(self)
        layout.setSpacing(20)
        self.name_input = QComboBox()
        self.name_input.setEditable(True)
        self.name_input.setInsertPolicy(QComboBox.NoInsert)
        self.name_input.setFont(QFont('Microsoft YaHei', 16))
        if product_names:
            self.name_input.addItems(product_names)
        if selected_name:
            self.name_input.setCurrentText(selected_name)
        self.name_input.lineEdit().setPlaceholderText('输入或选择商品名称')
        self.name_input.lineEdit().setMaxLength(MAX_NAME_LENGTH)
        self.name_input.lineEdit().setFont(QFont('Microsoft YaHei', 16))
        completer = QCompleter(product_names or [])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.name_input.setCompleter(completer)
        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, 999999)
        self.qty_input.setSuffix(' 个')
        self.qty_input.setFont(QFont('Microsoft YaHei', 16))
        self.note_input = QLineEdit()
        self.note_input.setMaxLength(MAX_NOTE_LENGTH)
        self.note_input.setPlaceholderText('可选，如供应商、批次号等')
        self.note_input.setFont(QFont('Microsoft YaHei', 16))
        for text in ['商品名称:', '入库数量:', '备注:']:
            lbl = QLabel(text)
            lbl.setFont(QFont('Microsoft YaHei', 16))
            if text == '商品名称:':
                layout.addRow(lbl, self.name_input)
            elif text == '入库数量:':
                layout.addRow(lbl, self.qty_input)
            else:
                layout.addRow(lbl, self.note_input)
        btn_layout = QHBoxLayout()
        btn_style = 'color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;'
        ok_btn = QPushButton('确认入库')
        cancel_btn = QPushButton('取消')
        ok_btn.setStyleSheet('background:#27ae60;{}'.format(btn_style))
        cancel_btn.setStyleSheet('background:#95a5a6;{}'.format(btn_style))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)


class StockOutDialog(QDialog):
    def __init__(self, parent=None, product_names=None, selected_name=''):
        super().__init__(parent)
        self.setWindowTitle('出库')
        self.setFixedSize(960, 520)
        layout = QFormLayout(self)
        layout.setSpacing(20)
        self.name_input = QComboBox()
        self.name_input.setEditable(True)
        self.name_input.setInsertPolicy(QComboBox.NoInsert)
        self.name_input.setFont(QFont('Microsoft YaHei', 16))
        if product_names:
            self.name_input.addItems(product_names)
        if selected_name:
            self.name_input.setCurrentText(selected_name)
        self.name_input.lineEdit().setPlaceholderText('输入或选择商品名称')
        self.name_input.lineEdit().setMaxLength(MAX_NAME_LENGTH)
        self.name_input.lineEdit().setFont(QFont('Microsoft YaHei', 16))
        completer = QCompleter(product_names or [])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.name_input.setCompleter(completer)
        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, 999999)
        self.qty_input.setSuffix(' 个')
        self.qty_input.setFont(QFont('Microsoft YaHei', 16))
        self.note_input = QLineEdit()
        self.note_input.setMaxLength(MAX_NOTE_LENGTH)
        self.note_input.setPlaceholderText('可选，如领用人、用途等')
        self.note_input.setFont(QFont('Microsoft YaHei', 16))
        for text in ['商品名称:', '出库数量:', '备注:']:
            lbl = QLabel(text)
            lbl.setFont(QFont('Microsoft YaHei', 16))
            if text == '商品名称:':
                layout.addRow(lbl, self.name_input)
            elif text == '出库数量:':
                layout.addRow(lbl, self.qty_input)
            else:
                layout.addRow(lbl, self.note_input)
        btn_layout = QHBoxLayout()
        btn_style = 'color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;'
        ok_btn = QPushButton('确认出库')
        cancel_btn = QPushButton('取消')
        ok_btn.setStyleSheet('background:#e74c3c;{}'.format(btn_style))
        cancel_btn.setStyleSheet('background:#95a5a6;{}'.format(btn_style))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)


class SearchDialog(QDialog):
    def __init__(self, parent=None, product_names=None):
        super().__init__(parent)
        self.setWindowTitle('查询库存')
        self.setFixedSize(960, 400)
        layout = QFormLayout(self)
        layout.setSpacing(20)
        self.name_input = QComboBox()
        self.name_input.setEditable(True)
        self.name_input.setInsertPolicy(QComboBox.NoInsert)
        self.name_input.setFont(QFont('Microsoft YaHei', 16))
        if product_names:
            self.name_input.addItems(product_names)
        self.name_input.lineEdit().setPlaceholderText('输入或选择商品名称')
        self.name_input.lineEdit().setMaxLength(MAX_NAME_LENGTH)
        self.name_input.lineEdit().setFont(QFont('Microsoft YaHei', 16))
        completer = QCompleter(product_names or [])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.name_input.setCompleter(completer)
        lbl = QLabel('商品名称:')
        lbl.setFont(QFont('Microsoft YaHei', 16))
        layout.addRow(lbl, self.name_input)
        btn_layout = QHBoxLayout()
        btn_style = 'color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;'
        ok_btn = QPushButton('查询')
        cancel_btn = QPushButton('取消')
        ok_btn.setStyleSheet('background:#f39c12;{}'.format(btn_style))
        cancel_btn.setStyleSheet('background:#95a5a6;{}'.format(btn_style))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)


class EditSelectDialog(QDialog):
    def __init__(self, parent=None, product_names=None):
        super().__init__(parent)
        self.setWindowTitle('选择编辑商品')
        self.setFixedSize(960, 400)
        layout = QFormLayout(self)
        layout.setSpacing(20)
        self.name_input = QComboBox()
        self.name_input.setEditable(True)
        self.name_input.setInsertPolicy(QComboBox.NoInsert)
        self.name_input.setFont(QFont('Microsoft YaHei', 16))
        if product_names:
            self.name_input.addItems(product_names)
        self.name_input.lineEdit().setPlaceholderText('输入或选择商品名称')
        self.name_input.lineEdit().setMaxLength(MAX_NAME_LENGTH)
        self.name_input.lineEdit().setFont(QFont('Microsoft YaHei', 16))
        completer = QCompleter(product_names or [])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.name_input.setCompleter(completer)
        lbl = QLabel('商品名称:')
        lbl.setFont(QFont('Microsoft YaHei', 16))
        layout.addRow(lbl, self.name_input)
        btn_layout = QHBoxLayout()
        btn_style = 'color:white;padding:10px 40px;border-radius:5px;font-size:36px;font-weight:bold;'
        ok_btn = QPushButton('编辑')
        cancel_btn = QPushButton('取消')
        ok_btn.setStyleSheet('background:#8e44ad;{}'.format(btn_style))
        cancel_btn.setStyleSheet('background:#95a5a6;{}'.format(btn_style))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)


class EditRecordDialog(QDialog):
    def __init__(self, parent=None, name='', pid=0, stock_in=None, stock_out=None):
        super().__init__(parent)
        self.setWindowTitle('编辑：{}'.format(name))
        self.setMinimumSize(1400, 1000)
        self.pid = pid
        self.stock_in = list(stock_in or [])
        self.stock_out = list(stock_out or [])
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel('商品：{}'.format(name))
        title.setFont(QFont('Microsoft YaHei', 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 入库记录
        in_group = QGroupBox('入库记录')
        in_group.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        in_layout = QVBoxLayout(in_group)
        self.in_table = QTableWidget()
        self.in_table.setFont(QFont('Microsoft YaHei', 14))
        self.in_table.setColumnCount(4)
        self.in_table.setHorizontalHeaderLabels(['时间', '数量', '备注', '操作'])
        self.in_table.horizontalHeader().setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        self.in_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.in_table.setColumnWidth(1, 160)
        self.in_table.setColumnWidth(2, 300)
        self.in_table.setColumnWidth(3, 120)
        self.in_table.verticalHeader().setDefaultSectionSize(36)
        self.in_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.in_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._reload_in_table()
        in_layout.addWidget(self.in_table)

        in_btn_layout = QHBoxLayout()
        add_in_btn = QPushButton('+ 添加入库')
        add_in_btn.setStyleSheet('background:#27ae60;color:white;padding:10px 30px;border-radius:5px;font-size:32px;font-weight:bold;')
        add_in_btn.clicked.connect(self._add_in_record)
        in_btn_layout.addStretch()
        in_btn_layout.addWidget(add_in_btn)
        in_layout.addLayout(in_btn_layout)
        layout.addWidget(in_group)

        # 出库记录
        out_group = QGroupBox('出库记录')
        out_group.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        out_layout = QVBoxLayout(out_group)
        self.out_table = QTableWidget()
        self.out_table.setFont(QFont('Microsoft YaHei', 14))
        self.out_table.setColumnCount(4)
        self.out_table.setHorizontalHeaderLabels(['时间', '数量', '备注', '操作'])
        self.out_table.horizontalHeader().setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        self.out_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.out_table.setColumnWidth(1, 160)
        self.out_table.setColumnWidth(2, 300)
        self.out_table.setColumnWidth(3, 120)
        self.out_table.verticalHeader().setDefaultSectionSize(36)
        self.out_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.out_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._reload_out_table()
        out_layout.addWidget(self.out_table)

        out_btn_layout = QHBoxLayout()
        add_out_btn = QPushButton('+ 添加出库')
        add_out_btn.setStyleSheet('background:#e74c3c;color:white;padding:10px 30px;border-radius:5px;font-size:32px;font-weight:bold;')
        add_out_btn.clicked.connect(self._add_out_record)
        out_btn_layout.addStretch()
        out_btn_layout.addWidget(add_out_btn)
        out_layout.addLayout(out_btn_layout)
        layout.addWidget(out_group)

        # 底部按钮
        bottom = QHBoxLayout()
        close_btn = QPushButton('完成')
        close_btn.setStyleSheet('background:#3498db;color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;')
        close_btn.clicked.connect(self.accept)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _reload_in_table(self):
        self.in_table.setUpdatesEnabled(False)
        self.in_table.setRowCount(len(self.stock_in))
        for i, r in enumerate(self.stock_in):
            self.in_table.setItem(i, 0, QTableWidgetItem(str(r['created_at'])))
            qty_item = QTableWidgetItem('+{}'.format(r['quantity']))
            qty_item.setForeground(Qt.darkGreen)
            self.in_table.setItem(i, 1, qty_item)
            self.in_table.setItem(i, 2, QTableWidgetItem(r['note'] or '-'))
            del_btn = QPushButton('X')
            del_btn.setStyleSheet('background:#e74c3c;color:white;padding:4px 12px;border-radius:3px;font-size:42px;font-weight:bold;')
            del_btn.clicked.connect(lambda checked, idx=i: self._delete_in(idx))
            self.in_table.setCellWidget(i, 3, del_btn)
        self.in_table.setUpdatesEnabled(True)

    def _reload_out_table(self):
        self.out_table.setUpdatesEnabled(False)
        self.out_table.setRowCount(len(self.stock_out))
        for i, r in enumerate(self.stock_out):
            self.out_table.setItem(i, 0, QTableWidgetItem(str(r['created_at'])))
            qty_item = QTableWidgetItem('-{}'.format(r['quantity']))
            qty_item.setForeground(Qt.red)
            self.out_table.setItem(i, 1, qty_item)
            self.out_table.setItem(i, 2, QTableWidgetItem(r['note'] or '-'))
            del_btn = QPushButton('X')
            del_btn.setStyleSheet('background:#e74c3c;color:white;padding:4px 12px;border-radius:3px;font-size:42px;font-weight:bold;')
            del_btn.clicked.connect(lambda checked, idx=i: self._delete_out(idx))
            self.out_table.setCellWidget(i, 3, del_btn)
        self.out_table.setUpdatesEnabled(True)

    def _delete_in(self, idx):
        if idx >= len(self.stock_in):
            return
        record = self.stock_in[idx]
        reply = QMessageBox.question(self, '确认删除',
                                     '确定删除入库记录：{}个？'.format(record['quantity']),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                with get_db() as conn:
                    conn.execute('DELETE FROM stock_in WHERE id=?', (record['id'],))
                    conn.commit()
                self.stock_in.pop(idx)
                self._reload_in_table()
            except sqlite3.Error as e:
                logger.error('删除入库记录失败: {}'.format(e))

    def _delete_out(self, idx):
        if idx >= len(self.stock_out):
            return
        record = self.stock_out[idx]
        reply = QMessageBox.question(self, '确认删除',
                                     '确定删除出库记录：{}个？'.format(record['quantity']),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                with get_db() as conn:
                    conn.execute('DELETE FROM stock_out WHERE id=?', (record['id'],))
                    conn.commit()
                self.stock_out.pop(idx)
                self._reload_out_table()
            except sqlite3.Error as e:
                logger.error('删除出库记录失败: {}'.format(e))

    def _add_in_record(self):
        dlg = AddRecordDialog(self, '入库')
        if dlg.exec_():
            qty = dlg.qty_input.value()
            note = sanitize_note(dlg.note_input.text())
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO stock_in (product_id, quantity, note, created_at) VALUES (?,?,?,?)',
                                 (self.pid, qty, note, now))
                    conn.commit()
                    new_record = conn.execute('SELECT * FROM stock_in WHERE product_id=? ORDER BY id DESC LIMIT 1',
                                              (self.pid,)).fetchone()
                self.stock_in.insert(0, new_record)
                self._reload_in_table()
            except sqlite3.Error as e:
                logger.error('添加入库记录失败: {}'.format(e))

    def _add_out_record(self):
        try:
            with get_db() as conn:
                row = conn.execute('''
                    SELECT
                        COALESCE((SELECT SUM(quantity) FROM stock_in WHERE product_id=?), 0) -
                        COALESCE((SELECT SUM(quantity) FROM stock_out WHERE product_id=?), 0) as remaining
                ''', (self.pid, self.pid)).fetchone()
                remaining = row['remaining']
        except sqlite3.Error as e:
            logger.error('查询库存失败: {}'.format(e))
            return
        if remaining <= 0:
            QMessageBox.warning(self, '库存不足', '当前无库存可出库')
            return
        dlg = AddRecordDialog(self, '出库', max_val=remaining)
        if dlg.exec_():
            qty = dlg.qty_input.value()
            note = sanitize_note(dlg.note_input.text())
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO stock_out (product_id, quantity, note, created_at) VALUES (?,?,?,?)',
                                 (self.pid, qty, note, now))
                    conn.commit()
                    new_record = conn.execute('SELECT * FROM stock_out WHERE product_id=? ORDER BY id DESC LIMIT 1',
                                              (self.pid,)).fetchone()
                self.stock_out.insert(0, new_record)
                self._reload_out_table()
            except sqlite3.Error as e:
                logger.error('添加出库记录失败: {}'.format(e))


class AddRecordDialog(QDialog):
    def __init__(self, parent=None, action='入库', max_val=999999):
        super().__init__(parent)
        self.setWindowTitle('添加{}'.format(action))
        self.setFixedSize(600, 300)
        layout = QFormLayout(self)
        layout.setSpacing(20)
        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, max_val)
        self.qty_input.setSuffix(' 个')
        self.qty_input.setFont(QFont('Microsoft YaHei', 16))
        self.note_input = QLineEdit()
        self.note_input.setMaxLength(MAX_NOTE_LENGTH)
        self.note_input.setPlaceholderText('可选')
        self.note_input.setFont(QFont('Microsoft YaHei', 16))
        for text, widget in [('数量:', self.qty_input), ('备注:', self.note_input)]:
            lbl = QLabel(text)
            lbl.setFont(QFont('Microsoft YaHei', 16))
            layout.addRow(lbl, widget)
        btn_layout = QHBoxLayout()
        btn_style = 'color:white;padding:8px 24px;border-radius:4px;font-size:16px;font-weight:bold;'
        ok_btn = QPushButton('确认{}'.format(action))
        cancel_btn = QPushButton('取消')
        if action == '入库':
            ok_btn.setStyleSheet('background:#27ae60;{}'.format(btn_style))
        else:
            ok_btn.setStyleSheet('background:#e74c3c;{}'.format(btn_style))
        cancel_btn.setStyleSheet('background:#95a5a6;{}'.format(btn_style))
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)


class SearchResultDialog(QDialog):
    def __init__(self, parent=None, name='', total_in=0, total_out=0, remaining=0):
        super().__init__(parent)
        self.setWindowTitle('查询结果')
        self.setFixedSize(1200, 800)
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        title = QLabel(name)
        title.setFont(QFont('Microsoft YaHei', 24, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(15)
        for label, value, color in [
            ('累计入库', '+{}'.format(total_in), '#27ae60'),
            ('累计出库', '-{}'.format(total_out), '#e74c3c'),
            ('当前余量', str(remaining), '#2980b9' if remaining > 0 else '#e74c3c'),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFont(QFont('Microsoft YaHei', 18))
            lbl.setAlignment(Qt.AlignCenter)
            val = QLabel(value)
            val.setFont(QFont('Microsoft YaHei', 26, QFont.Bold))
            val.setStyleSheet('color:{};'.format(color))
            val.setAlignment(Qt.AlignCenter)
            row.addWidget(lbl)
            row.addWidget(val)
            layout.addLayout(row)
        layout.addStretch()
        close_btn = QPushButton('关闭')
        close_btn.setStyleSheet('background:#3498db;color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;')
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)


class DetailDialog(QDialog):
    def __init__(self, parent=None, name='', stock_in=None, stock_out=None, total_in=0, total_out=0):
        super().__init__(parent)
        self.setWindowTitle('明细：{}'.format(name))
        self.setMinimumSize(1400, 1040)
        layout = QVBoxLayout(self)
        remaining = total_in - total_out
        info = QLabel('累计入库: {}    累计出库: {}    当前余量: {}'.format(total_in, total_out, remaining))
        info.setAlignment(Qt.AlignCenter)
        info.setFont(QFont('Microsoft YaHei', 18, QFont.Bold))
        layout.addWidget(info)
        in_group = QGroupBox('入库记录')
        in_group.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        in_layout = QVBoxLayout(in_group)
        in_table = QTableWidget()
        in_table.setFont(QFont('Microsoft YaHei', 14))
        in_table.setColumnCount(3)
        in_table.setHorizontalHeaderLabels(['时间', '数量', '备注'])
        in_table.horizontalHeader().setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        in_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        in_table.setColumnWidth(1, 160)
        in_table.setColumnWidth(2, 300)
        in_table.verticalHeader().setDefaultSectionSize(36)
        in_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        in_table.setRowCount(len(stock_in) if stock_in else 0)
        for i, r in enumerate(stock_in or []):
            in_table.setItem(i, 0, QTableWidgetItem(str(r['created_at'])))
            qty_item = QTableWidgetItem('+{}'.format(r['quantity']))
            qty_item.setForeground(Qt.darkGreen)
            in_table.setItem(i, 1, qty_item)
            in_table.setItem(i, 2, QTableWidgetItem(r['note'] or '-'))
        in_table.setMaximumHeight(300)
        in_layout.addWidget(in_table)
        layout.addWidget(in_group)
        out_group = QGroupBox('出库记录')
        out_group.setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        out_layout = QVBoxLayout(out_group)
        out_table = QTableWidget()
        out_table.setFont(QFont('Microsoft YaHei', 14))
        out_table.setColumnCount(3)
        out_table.setHorizontalHeaderLabels(['时间', '数量', '备注'])
        out_table.horizontalHeader().setFont(QFont('Microsoft YaHei', 14, QFont.Bold))
        out_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        out_table.setColumnWidth(1, 160)
        out_table.setColumnWidth(2, 300)
        out_table.verticalHeader().setDefaultSectionSize(36)
        out_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        out_table.setRowCount(len(stock_out) if stock_out else 0)
        for i, r in enumerate(stock_out or []):
            out_table.setItem(i, 0, QTableWidgetItem(str(r['created_at'])))
            qty_item = QTableWidgetItem('-{}'.format(r['quantity']))
            qty_item.setForeground(Qt.red)
            out_table.setItem(i, 1, qty_item)
            out_table.setItem(i, 2, QTableWidgetItem(r['note'] or '-'))
        out_table.setMaximumHeight(300)
        out_layout.addWidget(out_table)
        layout.addWidget(out_group)
        btn_style = 'color:white;padding:14px 50px;border-radius:6px;font-size:36px;font-weight:bold;'
        close_btn = QPushButton('关闭')
        close_btn.setStyleSheet('background:#3498db;{}'.format(btn_style))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


def excepthook(exc_type, exc_value, exc_tb):
    logger.error('未捕获的异常', exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


if __name__ == '__main__':
    sys.excepthook = excepthook
    init_db()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
