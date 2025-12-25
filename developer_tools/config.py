PORTRAIT_WINDOW_STYLESHEET = """
QWidget { background-color: #2c3e50; color: #ecf0f1; font-family: 'Helvetica Neue', Arial, sans-serif; }
QLabel { font-size: 12px; padding: 5px; }
QPushButton {
    background-color: #3986ae;
    color: #ffffff;
    border: none;
    padding: 5px;
    border-radius: 6px;
    font-weight: bold;
    min-width: 140px;
    font-size: 11px;
}
QPushButton:hover { background-color: #2980b9; }
QScrollBar:vertical {
    border: none;
    background: #2c3e50;
    width: 26px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #5dade2;
    min-height: 20px;
    border-radius: 5px;
    margin: 4px 7px;
}
QScrollBar::handle:vertical:hover {
    background: #3498db;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
}
QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
    border: none;
    background: #34495e;
    height: 14px;
    subcontrol-origin: margin;
    border-radius: 3px;
}
QScrollBar::sub-line:vertical:hover, QScrollBar::add-line:vertical:hover {
    background: #3f5f76;
}
QScrollBar::sub-line:vertical { subcontrol-position: top; }
QScrollBar::add-line:vertical { subcontrol-position: bottom; }
QScrollBar::up-arrow:vertical {
    image: url(data:image/png;base64,...);
    width: 12px; height: 12px;
    margin: 0px;
    padding: 0px;
}
QScrollBar::down-arrow:vertical {
    image: url(data:image/png;base64,...);
    width: 12px; height: 12px;
    background: transparent;
}
"""
CROP_APP_STYLESHEET = """
QWidget { background-color: #2c3e50; color: #ecf0f1; font-family: 'Helvetica Neue', Arial, sans-serif; }
QLabel { font-size: 12px; padding: 5px; }
QSlider::groove:horizontal { border: 1px solid #3986ae; height: 8px; background: #34495e; margin: 2px 0; }
QSlider::handle:horizontal { background: #3986ae; border: 1px solid #2980b9; width: 18px; margin: -2px 0; border-radius: 3px; }
QPushButton { 
    background-color: #3986ae; 
    color: #ffffff; 
    border: none; 
    padding: 10px 18px; 
    border-radius: 8px; 
    font-weight: bold; 
}
QPushButton:hover { background-color: #2980b9; }
"""
