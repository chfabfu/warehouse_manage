# warehouse_manage

本地库存管理系统 - PyQt5 + SQLite

## 功能

- 商品管理（新增/删除）
- 入库/出库（支持自动补全，库存不足拦截）
- 查询库存（弹窗显示入库/出库/余量）
- 查看明细（双击表格行，显示全部入库出库流水）
- 编辑记录（删除/添加单条入库出库记录）
- 导出/导入 CSV（自动备份数据库）

## 运行

```bash
# 安装依赖
pip install PyQt5

# 启动
python app.py
```

## 打包

```bash
pip install pyinstaller
pyinstaller -F -w --icon=tu_biao/tubiao.ico --add-data "tu_biao;tu_biao" --add-binary "<python路径>/Library/bin/sqlite3.dll;." app.py
```

## 环境要求

- Python 3.8+
- PyQt5
- Windows 7 及以上

## 开源协议

MIT License
