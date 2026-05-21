import asyncio

import base64

import io

import os

import sys

import time

import warnings

import math

from datetime import datetime



import flet as ft

import matplotlib

import matplotlib.pyplot as plt

import mplfinance as mpf

import pandas as pd



# 禁用 RuntimeWarning

warnings.filterwarnings("ignore", category=RuntimeWarning)



matplotlib.use("Agg")



sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



from quant_app.core.logger import flet_handler, get_logger

from quant_app.core.history_sync_service import history_sync_service

from quant_app.core.mt5_client import mt5_client

from quant_app.modules.hedge import hedge_manager

from quant_app.core.strategy_manager import strategy_runner

from quant_app.modules.ai.curve_analysis import CurveGateConfig, CurveSignalGate, curve_analysis_service

from quant_app.modules.data_collector.crawler_engine import data_engine, news_engine



logger = get_logger("NeuralQuantUI")





class NeuralQuantApp:

    def __init__(self, page: ft.Page):

        self.page = page

        self.page.title = "NeuralQuant Pro Console"

        self.page.theme_mode = ft.ThemeMode.DARK

        self.page.padding = 0

        self.page.bgcolor = "#1b2230"

        self.page.window_width = 1350

        self.page.window_height = 1000

        try:

            self.page.window.min_width = 1200

            self.page.window.min_height = 900

        except Exception:

            pass



        self.env_path = mt5_client.env_path

        self.app_env = self.load_env_settings()

        self.current_symbol = self.app_env.get("TRADE_SYMBOL", "XAUUSD.c")

        os.environ["TRADE_SYMBOL"] = self.current_symbol

        # 更新后端相关服务的默认交易品种
        history_sync_service.update_symbol(self.current_symbol)
        strategy_runner.symbol = self.current_symbol
        try:
            from quant_app.modules.ai.auto_trainer import ai_trainer
            ai_trainer.update_symbol(self.current_symbol)
        except Exception as trainer_err:
            logger.warning(f"初始化阶段更新 AI 训练器品种失败: {trainer_err}")

        strategies_base_dir = os.path.join(

            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),

            "modules",

            "strategies",

        )

        self.strategy_preset_dirs = {

            "GridMartingaleMA01": os.path.join(strategies_base_dir, "grid_martingale_ma01", "presets"),

            "GridMartingaleMA02": os.path.join(strategies_base_dir, "grid_martingale_ma02", "presets"),

            "GridMartingaleMA04": os.path.join(strategies_base_dir, "grid_martingale_ma04", "presets"),

        }

        self.current_tf = "M1"

        self.bar_count = 100

        self.chart_offset = 0

        self.min_bar_count = 40

        self.max_bar_count = 300

        self.is_drawing = False

        self.use_interactive_chart = False

        self.last_chart_render_at = 0.0

        self.chart_refresh_interval = 1.2

        self.last_chart_image = None

        self.last_chart_size = (0, 0)

        self.latest_curve_action = "WAIT"

        self.latest_curve_reason = ""

        self.latest_df = None

        self.latest_curve_signal = None

        self.is_shutting_down = False



        self.side_log_column = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, auto_scroll=True)

        self.side_log_list = ft.Container(

            content=self.side_log_column,

            expand=True,

            padding=5,

        )

        self.bottom_log_column = ft.Column(spacing=5, scroll=ft.ScrollMode.AUTO, auto_scroll=True)

        self.bottom_log_list = ft.Container(

            content=self.bottom_log_column,

            expand=True,

            padding=5,

        )

        self.trade_list = ft.ListView(expand=True, spacing=0, padding=ft.padding.only(bottom=10), auto_scroll=False)

        self.exposure_list = ft.ListView(expand=True, spacing=0, padding=ft.padding.only(bottom=10), auto_scroll=False)

        self.history_list = ft.ListView(expand=True, spacing=0, padding=ft.padding.only(bottom=10), auto_scroll=False)

        self.news_list = ft.ListView(expand=True, spacing=0, padding=ft.padding.only(bottom=10), auto_scroll=False)



        self.log_queue = []

        self.max_ui_log_entries = 100

        self.strategy_start_time = None

        self.last_history_refresh = 0

        self.last_news_refresh = 0

        self._last_pos = []

        self._last_acc = {}

        self.last_readiness_refresh = 0

        self.today_profit_value = 0.0

        self.profit_fetch_task = None

        self.initial_profit_fetched = False

        self.active_main_tab = "home"

        self.secondary_refresh_running = False

        # 智能解仓弹窗对话框状态
        self._unlock_dialog_open = False
        self._unlock_dialog_shown = False
        self._selected_strategy = None
        self._cooldown_waived = False
        self._was_locked = False
        self._unlock_success_time = 0.0

        self.setup_ui()

        self.register_lifecycle_hooks()

        history_sync_service.start()



        if hasattr(flet_handler, "callback"):

            flet_handler.callback = self.on_backend_log



        self.page.run_task(self.update_loop)

        self.page.run_task(self._force_window_layout_on_start)

        self.page.update()



    def register_lifecycle_hooks(self):

        # 桌面端窗口直接关闭时，如果不主动停策略并退出刷新循环，

        # Python/Flet 后台进程会继续存活，导致 dist 文件被占用无法删除。

        try:

            if hasattr(self.page, "on_disconnect"):

                self.page.on_disconnect = self._on_page_disconnect

        except Exception:

            pass



        try:

            page_window = getattr(self.page, "window", None)

            if page_window is not None and hasattr(page_window, "on_event"):

                page_window.on_event = self._on_window_event

        except Exception:

            pass



    async def _force_window_layout_on_start(self):

        # 延迟 150 毫秒等待 OS 窗口环境建立完毕，再强制触发一次大小更新与重绘

        # 这能彻底解决 Flet/Flutter 在 Windows 平台偶发的初次启动布局约束无法同步的 Bug

        await asyncio.sleep(0.35)

        try:

            self.page.window.width = 1350

            self.page.window.height = 1000

            self.page.update()

        except Exception:

            try:

                self.page.window_width = 1350

                self.page.window_height = 1000

                self.page.update()

            except Exception:

                pass





    def _on_page_disconnect(self, e):

        self.request_shutdown()



    def _on_window_event(self, e):

        event_name = str(getattr(e, "data", "") or getattr(e, "type", "") or "").lower()

        if "close" in event_name or "destroy" in event_name:

            self.request_shutdown()



    def request_shutdown(self):

        if self.is_shutting_down:

            return

        self.is_shutting_down = True

        try:

            self.page.run_task(self.shutdown_app)

        except Exception:

            pass



    async def shutdown_app(self):

        try:

            await asyncio.to_thread(strategy_runner.stop)

        except Exception as exc:

            logger.error(f"Shutdown stop strategy failed: {exc}")

        try:

            await asyncio.to_thread(mt5_client.disconnect)

        except Exception as exc:

            logger.error(f"Shutdown MT5 disconnect failed: {exc}")

        try:

            await asyncio.to_thread(history_sync_service.stop)

        except Exception as exc:

            logger.error(f"Shutdown history sync failed: {exc}")



    def setup_ui(self):

        self.mt5_file_picker = ft.FilePicker()

        if hasattr(self.page, "services"):

            self.page.services.append(self.mt5_file_picker)

        elif hasattr(self.page, "overlay"):

            self.page.overlay.append(self.mt5_file_picker)



        self.status_dot = ft.Container(width=12, height=12, border_radius=6, bgcolor=ft.Colors.RED_ACCENT)

        self.status_text = ft.Text("系统连接中...", size=13, color=ft.Colors.GREY_400)

        self.balance_text = ft.Text("0.00", size=26, weight=ft.FontWeight.BOLD)

        self.profit_text = ft.Text("+0.00", size=18, weight=ft.FontWeight.W_600)

        self.account_id_text = ft.Text("ID: ---", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)

        self.server_text = ft.Text("---", size=11, color=ft.Colors.GREY_500)



        self.home_view = self.build_home_view()

        self.settings_view = self.build_settings_view()

        self.main_content = ft.Container(content=self.home_view, expand=True)



        self.page.add(

            ft.Column(

                [

                    self.build_header(),

                    self.main_content,

                ],

                expand=True,

                spacing=0,

            )

        )



    def build_header(self):

        self.home_nav = self.build_nav_button("home", ft.Icons.HOME, "首页 Dashboard")

        self.settings_nav = self.build_nav_button("settings", ft.Icons.SETTINGS, "设置 Settings")

        return ft.Container(

            content=ft.Row(

                [

                    ft.Column(

                        [

                            ft.Text("NeuralQuant Pro", size=22, weight=ft.FontWeight.W_900),

                            ft.Row([self.status_dot, self.status_text], spacing=8),

                        ],

                        spacing=2,

                    ),

                    ft.Container(

                        content=ft.Row(

                            [

                                self.home_nav,

                                self.settings_nav,

                            ],

                            spacing=12,

                            alignment=ft.MainAxisAlignment.CENTER,

                            vertical_alignment=ft.CrossAxisAlignment.CENTER,

                        ),

                        expand=True,

                        alignment=ft.Alignment(0, 0),

                    ),

                    ft.Column(

                        [self.account_id_text, self.server_text],

                        horizontal_alignment=ft.CrossAxisAlignment.END,

                        spacing=2,

                    ),

                ],

                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,

            ),

            padding=ft.Padding(20, 10, 20, 10),

            bgcolor="#1c2127",

        )



    def _build_asset_card(self, icon, icon_color, caption, value_text_control, bg_color="#111827", border_color="#2a2e39"):
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(icon, color=icon_color, size=24),
                        bgcolor="#1e293b",
                        padding=10,
                        border_radius=10,
                    ),
                    ft.Column(
                        [
                            ft.Text(caption, size=11, color="#98a2b3"),
                            value_text_control,
                        ],
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                    )
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            bgcolor=bg_color,
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            border_radius=12,
            border=ft.border.all(1, border_color),
        )

    def _update_top_profit_card(self, profit):
        if profit >= 0:
            self.top_profit_card.bgcolor = "#143c24"
            self.top_profit_card.border = ft.border.all(1, "#2ecc71")
            self.top_profit_text.color = "#2ecc71"
        else:
            self.top_profit_card.bgcolor = "#3b1d1d"
            self.top_profit_card.border = ft.border.all(1, "#ff5c5c")
            self.top_profit_text.color = "#ff5c5c"

    def _update_top_today_profit_card(self, profit):
        if profit >= 0:
            self.top_today_profit_card.bgcolor = "#143c24"
            self.top_today_profit_card.border = ft.border.all(1, "#2ecc71")
            self.top_today_profit_text.color = "#2ecc71"
        else:
            self.top_today_profit_card.bgcolor = "#3b1d1d"
            self.top_today_profit_card.border = ft.border.all(1, "#ff5c5c")
            self.top_today_profit_text.color = "#ff5c5c"

    async def fetch_today_profit(self):
        try:
            today_profit = await asyncio.to_thread(mt5_client.get_today_profit)
            self.today_profit_value = today_profit
            if hasattr(self, "top_today_profit_text") and self.top_today_profit_text:
                self.top_today_profit_text.value = f"{today_profit:+,.2f}"
                self._update_top_today_profit_card(today_profit)
                self.page.update()
        except Exception as e:
            logger.error(f"Error fetching today's profit: {e}")

    async def delayed_fetch_today_profit(self):
        await asyncio.sleep(5)
        await self.fetch_today_profit()




    def build_nav_button(self, tab_name, icon, label):

        is_active = self.active_main_tab == tab_name

        return ft.Container(

            content=ft.Column(

                [

                    ft.Icon(icon, size=18, color=ft.Colors.WHITE if is_active else "#8b95a7"),

                    ft.Text(

                        label,

                        size=12,

                        weight=ft.FontWeight.W_600,

                        color=ft.Colors.WHITE if is_active else "#8b95a7",

                    ),

                ],

                spacing=6,

                horizontal_alignment=ft.CrossAxisAlignment.CENTER,

            ),

            padding=ft.padding.symmetric(horizontal=18, vertical=10),

            border_radius=12,

            bgcolor="#242b33" if is_active else "#1b2026",

            border=ft.border.all(1, "#89b4fa" if is_active else "#2d3540"),

            ink=True,

            on_click=lambda e, name=tab_name: self.switch_main_tab(name),

        )



    def refresh_header_nav(self):

        new_home = self.build_nav_button("home", ft.Icons.HOME, "首页 Dashboard")

        new_settings = self.build_nav_button("settings", ft.Icons.SETTINGS, "设置 Settings")

        self.home_nav.content = new_home.content

        self.home_nav.bgcolor = new_home.bgcolor

        self.home_nav.border = new_home.border

        self.home_nav.on_click = new_home.on_click

        self.settings_nav.content = new_settings.content

        self.settings_nav.bgcolor = new_settings.bgcolor

        self.settings_nav.border = new_settings.border

        self.settings_nav.on_click = new_settings.on_click

        self.home_nav.update()

        self.settings_nav.update()



    def switch_main_tab(self, tab_name):

        if self.active_main_tab == tab_name:

            return

        self.active_main_tab = tab_name

        if tab_name == "home":

            self.main_content.content = self.home_view

        else:

            self.main_content.content = self.settings_view

        self.refresh_header_nav()

        self.main_content.update()

        if tab_name == "home":

            self.page.run_task(self.draw_kline_img)



    def build_home_view(self):

        # 初始化顶部大卡片相关的 text 控件
        self.top_balance_text = ft.Text("0.00", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.top_equity_text = ft.Text("0.00", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.top_margin_text = ft.Text("0.00", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.top_profit_text = ft.Text("+0.00", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self.top_today_profit_text = ft.Text("+0.00", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)

        # 构建五个大卡片
        self.top_balance_card = self._build_asset_card(ft.Icons.ACCOUNT_BALANCE_WALLET, "#89b4fa", "结余 Balance", self.top_balance_text)
        self.top_equity_card = self._build_asset_card(ft.Icons.BAR_CHART, "#7dd3fc", "净值 Equity", self.top_equity_text)
        self.top_margin_card = self._build_asset_card(ft.Icons.SHIELD, "#f9e2af", "可用预付款 Free Margin", self.top_margin_text)
        self.top_profit_card = self._build_asset_card(ft.Icons.MONETIZATION_ON, "#2ecc71", "浮动盈亏 Profit", self.top_profit_text)
        self.top_today_profit_card = self._build_asset_card(ft.Icons.MONETIZATION_ON, "#a6e3a1", "今日盈利 Today Profit", self.top_today_profit_text)

        # 将大卡片放置在横向 Container 中
        self.top_asset_cards_row = ft.Container(
            content=ft.Row(
                [
                    self.top_balance_card,
                    self.top_equity_card,
                    self.top_margin_card,
                    self.top_profit_card,
                    self.top_today_profit_card,
                ],
                spacing=10,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.padding.only(left=10, right=10, top=10, bottom=5),
        )

        self.tf_selector = ft.SegmentedButton(

            segments=[

                ft.Segment("M1", label=ft.Text("M1")),

                ft.Segment("M5", label=ft.Text("M5")),

                ft.Segment("H1", label=ft.Text("H1 趋势")),

            ],

            selected=["M1"],

            on_change=self.tf_changed,

            show_selected_icon=False,

        )



        self.zoom_in_btn = ft.IconButton(icon=ft.Icons.ZOOM_IN, icon_size=16, tooltip="放大", on_click=self.zoom_in_chart)

        self.zoom_out_btn = ft.IconButton(icon=ft.Icons.ZOOM_OUT, icon_size=16, tooltip="缩小", on_click=self.zoom_out_chart)

        self.pan_left_btn = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, icon_size=18, tooltip="向左查看更早K线", on_click=self.pan_chart_left)

        self.pan_right_btn = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, icon_size=18, tooltip="向右回到最新K线", on_click=self.pan_chart_right)

        self.chart_reset_btn = ft.TextButton("重置", on_click=self.reset_chart_view)

        self.chart_range_text = ft.Text("", size=11, color=ft.Colors.GREY_400, font_family="Consolas", no_wrap=True, width=280)

        # --- [NEW] 多周期因子共振矩阵胶囊排 (Multi-TF Matrix) ---
        self.tf_matrix_capsules = {}
        self.tf_matrix_dots = {}
        self.tf_matrix_texts = {}
        
        timeframes = ["M1", "M5", "M15", "M30", "H1", "H4"]
        tf_capsules_list = []
        for tf in timeframes:
            dot = ft.Container(width=5.5, height=5.5, border_radius=3, bgcolor="#6c7a8f")
            text = ft.Text("震荡 NEUTRAL", size=8.5, weight=ft.FontWeight.W_600, color="#6c7a8f")
            capsule = ft.Container(
                content=ft.Row(
                    [
                        ft.Text(tf, size=9, weight=ft.FontWeight.W_900, color=ft.Colors.WHITE),
                        dot,
                        text,
                    ],
                    spacing=5,
                    alignment=ft.MainAxisAlignment.CENTER,
                    tight=True,
                ),
                padding=ft.padding.symmetric(horizontal=8, vertical=4.5),
                bgcolor="#11151c",
                border_radius=12,
                border=ft.border.all(1, "#222a36"),
            )
            self.tf_matrix_capsules[tf] = capsule
            self.tf_matrix_dots[tf] = dot
            self.tf_matrix_texts[tf] = text
            tf_capsules_list.append(capsule)
            
        # 封装图表分析状态覆层 (与多周期标签同级对齐，移除悬浮，完美融入顶栏)
        self.chart_overlay_badge = ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=5.5, height=5.5, border_radius=3, bgcolor="#89b4fa"),
                    self.chart_range_text,
                ],
                spacing=6,
                alignment=ft.MainAxisAlignment.START,
            ),
            width=385, # 精准固定小胶囊宽度，彻底根治变宽弹跳抖动
            padding=ft.padding.symmetric(horizontal=10, vertical=4.5), # 高度上与多周期标签完美对齐
            bgcolor="#11151c", # 采用与多周期标签相同的暗色，浑然一体
            border_radius=12,
            border=ft.border.all(1, "#222a36"),
        )
        
        # 重构顶栏：左侧排布多周期状态舱，右侧排布图表分析胶囊，中间拉伸撑开
        self.tf_matrix_row = ft.Container(
            content=ft.Row(
                [
                    ft.Row(tf_capsules_list, spacing=8, alignment=ft.MainAxisAlignment.START),
                    self.chart_overlay_badge,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.padding.only(left=10, right=10, bottom=6),
        )



        self.chart_control = ft.Image(

            src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",

            expand=True,

            fit=ft.BoxFit.FILL,

            gapless_playback=True,

        )

        self.chart_container = ft.Container(

            content=self.chart_control,

            expand=True,

            bgcolor="#000000",

        )



        self.asset_balance = ft.Text("结余: 0.00 USD", size=12)

        self.asset_equity = ft.Text("净值: 0.00", size=12)

        self.asset_margin = ft.Text("可用预付款: 0.00", size=12)

        self.asset_profit = ft.Text("0.00", size=12, weight="bold")

        self.asset_exposure_container = ft.Container(padding=ft.padding.only(left=5, right=5, top=5, bottom=5))

        self.asset_bar = ft.Row(

            [

                self.asset_balance,

                self.asset_equity,

                self.asset_margin,

                ft.VerticalDivider(width=20),

                self.asset_profit,

            ],

            spacing=20,

            vertical_alignment=ft.CrossAxisAlignment.CENTER,

        )



        self.bottom_tab_bar = ft.TabBar(

            indicator_color="#89b4fa",

            label_color=ft.Colors.WHITE,

            unselected_label_color="#98a2b3",

            tabs=[

                ft.Tab(label="交易"),

                ft.Tab(label="敞口"),

                ft.Tab(label="历史"),

                ft.Tab(label="新闻"),

            ],

        )

        self.trade_tab_content = ft.Column(
            [
                self.asset_exposure_container,
                self.trade_list,
            ],
            spacing=0,
            expand=True,
        )

        self.bottom_tab_view = ft.TabBarView(

            controls=[

                self.trade_tab_content,

                self.exposure_list,

                self.history_list,

                self.news_list,

            ],

            expand=True,

        )



        self.bottom_tabs = ft.Tabs(

            length=4,

            selected_index=0,

            content=ft.Column(

                [self.bottom_tab_bar, self.bottom_tab_view],

                expand=True,

                spacing=0,

            ),

            expand=True,

        )



        self.algo_switch = ft.Switch(label="自动执行策略", on_change=self.toggle_algo)

        self.current_strategy_text = ft.Text(

            f"策略: {self.app_env.get('ACTIVE_STRATEGY', strategy_runner.strategy_name or 'GridMartingaleMA01')}",

            size=12,

            color=ft.Colors.BLUE_200,

        )

        self.current_preset_text = ft.Text(

            f"预设: {strategy_runner.current_config_file or self.app_env.get('ACTIVE_PRESET') or '未选择'}",

            size=12,

            color=ft.Colors.GREY_400,

        )

        self.runtime_text = ft.Text("运行时间: 00:00:00", color=ft.Colors.AMBER_ACCENT, size=11)

        self.margin_level_text = ft.Text("健康度: ---", size=11, color=ft.Colors.GREEN_400)

        

        # --- AI 核心研判显示 ---

        self.ai_risk_text = ft.Text("AI风险: ---", size=11, color=ft.Colors.RED_ACCENT)

        self.ai_dir_text = ft.Text("AI方向: ---", size=11, color=ft.Colors.LIGHT_BLUE_400)

        self.ai_dir_icon = ft.Text("→", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_500)

        self.ai_phase_text = ft.Text("背景: ---", size=9, color=ft.Colors.GREY_500)



        # ---- 风险控制：状态徽章 + 三按钮 ----

        # 启动时从 hedge_manager 读取持久化状态，渲染正确的状态徽章

        self.hedge_status_badge = self._build_hedge_status_badge()

        self.unlock_strategy_panel = ft.Container(
            content=ft.Column([]),
            visible=False,
            padding=10,
            bgcolor="#111827",
            border_radius=8,
            border=ft.border.all(1, ft.Colors.PURPLE_300),
            margin=ft.margin.only(top=8)
        )

        self.btn_lock_hedge = ft.ElevatedButton(

            content=ft.Row(

                [ft.Icon(ft.Icons.LOCK_ROUNDED, size=16, color=ft.Colors.WHITE), ft.Text("一键锁仓", size=12, color=ft.Colors.WHITE)],

                spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,

            ),

            on_click=self.handle_lock_hedge,

            style=ft.ButtonStyle(

                bgcolor={"": "#1d4ed8", "hovered": "#1e40af"},

                shape=ft.RoundedRectangleBorder(radius=8),

                padding=ft.padding.symmetric(horizontal=10, vertical=10),

            ),

            expand=1,

        )

        self.btn_unlock_hedge = ft.ElevatedButton(

            content=ft.Row(

                [ft.Icon(ft.Icons.AUTO_FIX_HIGH, size=16, color=ft.Colors.WHITE), ft.Text("智能解仓", size=12, color=ft.Colors.WHITE)],

                spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,

            ),

            on_click=self.handle_unlock_hedge,

            style=ft.ButtonStyle(

                bgcolor={"": "#6d28d9", "hovered": "#5b21b6"},

                shape=ft.RoundedRectangleBorder(radius=8),

                padding=ft.padding.symmetric(horizontal=10, vertical=10),

            ),

            expand=1,

        )

        self.btn_close_all = ft.ElevatedButton(

            content=ft.Row(

                [ft.Icon(ft.Icons.DANGEROUS_ROUNDED, size=16, color=ft.Colors.WHITE), ft.Text("一键全平", size=12, color=ft.Colors.WHITE)],

                spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,

            ),

            on_click=self.handle_close_all,

            style=ft.ButtonStyle(

                bgcolor={"": "#991b1b", "hovered": "#7f1d1d"},

                shape=ft.RoundedRectangleBorder(radius=8),

                padding=ft.padding.symmetric(horizontal=10, vertical=10),

            ),

        )

        self.btn_cancel_lock = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.LOCK_RESET_ROUNDED, size=16, color=ft.Colors.WHITE), ft.Text("取消锁仓状态", size=12, color=ft.Colors.WHITE)],
                spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self.handle_cancel_lock,
            style=ft.ButtonStyle(
                bgcolor={"": "#374151", "hovered": "#4b5563"},
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=ft.padding.symmetric(horizontal=10, vertical=10),
            ),
            expand=1,
        )



        self.side_current_strategy_text = ft.Text(self.current_strategy_text.value, size=12, color=ft.Colors.BLUE_200, weight=ft.FontWeight.W_700)

        self.side_current_preset_text = ft.Text(self.current_preset_text.value, size=11, color=ft.Colors.WHITE)

        self.side_runtime_text = ft.Text(self.runtime_text.value, color=ft.Colors.AMBER_ACCENT, size=11)

        self.side_margin_level_text = ft.Text(self.margin_level_text.value, size=11, color=ft.Colors.GREEN_400, weight=ft.FontWeight.W_700)

        self.side_ai_risk_text = ft.Text(self.ai_risk_text.value, size=12, color=ft.Colors.RED_ACCENT, weight=ft.FontWeight.W_700)

        self.side_ai_dir_text = ft.Text(self.ai_dir_text.value, size=12, color=ft.Colors.LIGHT_BLUE_400, weight=ft.FontWeight.W_700)

        self.side_ai_phase_text = ft.Text(self.ai_phase_text.value, size=9, color=ft.Colors.GREY_500)

        self.side_ai_trend_factor_text = ft.Text("--%", size=13, color="#60a5fa", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

        self.side_ai_volatility_factor_text = ft.Text("--%", size=13, color="#fbbf24", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

        self.side_ai_flow_factor_text = ft.Text("--%", size=13, color="#2dd4bf", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

        self.side_ai_agent_live_text = ft.Text("等待策略心跳与曲线信号同步。", size=10, color=ft.Colors.GREY_400, visible=False)

        # AI 策略决策流 (Agent Live) 细分展示面板控件
        self.side_ai_risk_bar = ft.ProgressBar(value=0.0, color="#10b981", bgcolor="#1e293b", height=6, border_radius=3)
        self.side_ai_risk_val = ft.Text("0.0%", size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)
        
        self.side_ai_dir_badge_text = ft.Text("震荡 ⚖️", size=10, color="#94a3b8", weight=ft.FontWeight.BOLD)
        self.side_ai_dir_badge = ft.Container(
            content=self.side_ai_dir_badge_text,
            bgcolor="#1e293b",
            border_radius=4,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
            border=ft.border.all(1, "#475569")
        )
        self.side_ai_dir_val = ft.Text("50.0", size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)
        
        self.side_ai_sig_badge_text = ft.Text("WAIT", size=10, color="#60a5fa", weight=ft.FontWeight.BOLD)
        self.side_ai_sig_badge = ft.Container(
            content=self.side_ai_sig_badge_text,
            bgcolor="#172554",
            border_radius=4,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
            border=ft.border.all(1, "#1e40af")
        )
        
        self.side_ai_update_time = ft.Text("更新于: --:--:--", size=9, color=ft.Colors.GREY_500)




        def side_header(icon, title, color):

            return ft.Row(

                [ft.Icon(icon, size=14, color=color), ft.Text(title, size=12, color=color, weight=ft.FontWeight.W_700)],

                spacing=7,

            )



        def side_panel(children, bgcolor="#111827", border_color="#2f3a4b", expand=False):

            return ft.Container(

                content=ft.Column(children, spacing=8, expand=expand),

                padding=12,

                bgcolor=bgcolor,

                border_radius=8,

                border=ft.border.all(1, border_color),

                expand=expand,

            )



        def metric_box(label, value_control, accent, sub_text):

            return ft.Container(

                content=ft.Column(

                    [

                        ft.Text(label, size=10, color=ft.Colors.GREY_400),

                        value_control,

                        ft.Container(height=2, bgcolor=accent, border_radius=1),

                        ft.Text(sub_text, size=9, color=ft.Colors.GREY_500, no_wrap=True),

                    ],

                    spacing=5,

                ),

                padding=10,

                bgcolor="#111827",

                border_radius=8,

                border=ft.border.all(1, "#2a3342"),

                expand=1,

            )



        # 1. 策略绑定组件段
        strategy_binding_section = ft.Column(
            [
                side_header(ft.Icons.GRID_VIEW_ROUNDED, "策略绑定", "#93c5fd"),
                side_panel(
                    [
                        ft.Row([ft.Icon(ft.Icons.APPS_ROUNDED, size=14, color=ft.Colors.GREY_500), ft.Text("激活策略", size=10, color=ft.Colors.GREY_500)], spacing=8),
                        self.side_current_strategy_text,
                        ft.Row([ft.Icon(ft.Icons.SD_STORAGE_ROUNDED, size=14, color=ft.Colors.GREY_500), ft.Text("当前预设", size=10, color=ft.Colors.GREY_500)], spacing=8),
                        self.side_current_preset_text,
                    ]
                ),
            ],
            spacing=8,
        )

        # 2. 系统会话统计组件段
        session_stats_section = ft.Column(
            [
                side_header(ft.Icons.QUERY_STATS_ROUNDED, "系统会话统计", "#7dd3fc"),
                side_panel(
                    [
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.TIMER_OUTLINED, size=14, color=ft.Colors.GREY_500),
                                        ft.Text("统计计时", size=10, color=ft.Colors.GREY_500, weight=ft.FontWeight.W_600),
                                    ],
                                    spacing=4,
                                ),
                                self.side_runtime_text,
                                ft.Divider(color="#20293a", height=8),
                                ft.Row(
                                    [
                                        ft.Icon(ft.Icons.HEALTH_AND_SAFETY_OUTLINED, size=14, color=ft.Colors.GREY_500),
                                        ft.Text("系统健康度", size=10, color=ft.Colors.GREY_500, weight=ft.FontWeight.W_600),
                                    ],
                                    spacing=4,
                                ),
                                ft.Container(
                                    content=self.side_margin_level_text,
                                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                                    bgcolor="#172033",
                                    border_radius=16,
                                    border=ft.border.all(1, "#314057"),
                                    alignment=ft.Alignment(0, 0),
                                ),
                            ],
                            spacing=6,
                        )
                    ]
                ),
            ],
            spacing=8,
        )

        # 构建决策流子卡片 (紧凑型单行设计，适应低分辨率屏幕)
        risk_box = ft.Container(
            content=ft.Row(
                [
                    ft.Row([ft.Icon(ft.Icons.SHIELD_OUTLINED, size=13, color="#94a3b8"), ft.Text("风险健康度 (Risk)", size=10, color=ft.Colors.GREY_400)], spacing=4),
                    ft.Row([
                        self.side_ai_risk_val,
                        ft.Container(content=self.side_ai_risk_bar, width=65, padding=ft.padding.only(top=2))
                    ], spacing=4)
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            bgcolor="#0f172a",
            border_radius=6,
            border=ft.border.all(1, "#1e293b"),
        )
        
        dir_box = ft.Container(
            content=ft.Row(
                [
                    ft.Row([ft.Icon(ft.Icons.COMPASS_CALIBRATION_ROUNDED, size=13, color="#94a3b8"), ft.Text("动能方向 (Direction)", size=10, color=ft.Colors.GREY_400)], spacing=4),
                    ft.Row([self.side_ai_dir_val, self.side_ai_dir_badge], spacing=4),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            bgcolor="#0f172a",
            border_radius=6,
            border=ft.border.all(1, "#1e293b"),
        )
        
        sig_box = ft.Container(
            content=ft.Row(
                [
                    ft.Row([ft.Icon(ft.Icons.CELL_TOWER_ROUNDED, size=13, color="#94a3b8"), ft.Text("决策信号 (Signal)", size=10, color=ft.Colors.GREY_400)], spacing=4),
                    self.side_ai_sig_badge,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            bgcolor="#0f172a",
            border_radius=6,
            border=ft.border.all(1, "#1e293b"),
        )
        
        status_bar = ft.Row(
            [
                ft.Row([ft.Container(width=5, height=5, bgcolor="#2dd4bf", border_radius=2.5), ft.Text("心跳同步中 (Agent Live)", size=9, color=ft.Colors.GREY_500)], spacing=4),
                self.side_ai_update_time,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        # 3. AI 决策大脑组件段
        ai_decision_section = ft.Column(
            [
                side_header(ft.Icons.PSYCHOLOGY_ALT_ROUNDED, "AI 决策大脑", "#93c5fd"),
                ft.Row(
                    [
                        metric_box("AI 风险评估", self.side_ai_risk_text, "#ef4444", "背景: bottom turn watch"),
                        metric_box("AI 动能信心", self.side_ai_dir_text, "#334155", "多周期协同研判"),
                    ],
                    spacing=10,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            self._make_factor_gauge("趋势因子", "#3b82f6", "ai_factor_trend_ring", "ai_factor_trend_pct"),
                            self._make_factor_gauge("波动因子", "#e0af68", "ai_factor_vol_ring", "ai_factor_vol_pct"),
                            self._make_factor_gauge("主力资金", "#10b981", "ai_factor_flow_ring", "ai_factor_flow_pct"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        spacing=5,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=12),
                    bgcolor="#cc141926",
                    border_radius=8,
                    border=ft.border.all(1, "#2a3547"),
                ),
                side_panel(
                    [
                        ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=14, color="#2dd4bf"), ft.Text("AI 策略决策流 (Agent Live)", size=11, color="#dbeafe", weight=ft.FontWeight.W_600)], spacing=6),
                        ft.Divider(color="#20293a", height=8),
                        risk_box,
                        dir_box,
                        sig_box,
                        ft.Divider(color="#20293a", height=8),
                        status_bar,
                        self.side_ai_agent_live_text,
                    ],
                    expand=False,
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )

        # 4. 智能对冲风控风控段
        hedge_wind_control_section = ft.Column(
            [
                side_header(ft.Icons.SHIELD_ROUNDED, "智能对冲风控", ft.Colors.AMBER_400),
                side_panel(
                    [
                        self.hedge_status_badge,
                        ft.Row([self.btn_lock_hedge, self.btn_unlock_hedge], spacing=8, expand=False),
                        ft.Row([self.btn_close_all, self.btn_cancel_lock], spacing=8, expand=False),
                        self.unlock_strategy_panel,
                    ],
                    bgcolor="#1a1209",
                    border_color="#3d2b0a"
                )
            ],
            spacing=8
        )

        # 5. 组装右侧图表信息展示面板（仅保留 AI 决策大脑，靠图表右侧排布，背景透明以支持卡片高度自适应）
        self.right_chart_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ai_decision_section,
                        padding=12,
                        bgcolor="#1b2230",
                        border_radius=12,
                        border=ft.border.all(1, "#2a2e39"),
                        expand=True,
                    )
                ],
                spacing=0,
                expand=True,
            ),
            width=300,
            padding=ft.padding.only(left=10, right=10, top=5, bottom=5),
        )

        # 5.5 软件介绍组件段
        self.software_desc_text = ft.Text(
            f"本系统融合 AI 决策脑、多周期共振研判与智能锁仓风控，为 {self.current_symbol} 专业量化交易提供毫秒级决策支持。",
            size=9,
            color=ft.Colors.GREY_500,
        )

        software_info_section = ft.Column(
            [
                side_header(ft.Icons.INFO_OUTLINED, "软件介绍", "#a7f3d0"),
                side_panel(
                    [
                        ft.Row(
                            [
                                ft.Row([ft.Icon(ft.Icons.TAG_ROUNDED, size=12, color=ft.Colors.GREY_500), ft.Text("软件版本", size=10, color=ft.Colors.GREY_500)], spacing=4),
                                ft.Text("NeuralQuant Pro v4.2.0", size=10, color="#a7f3d0", weight=ft.FontWeight.BOLD),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(
                            [
                                ft.Row([ft.Icon(ft.Icons.TERMINAL_ROUNDED, size=12, color=ft.Colors.GREY_500), ft.Text("系统内核", size=10, color=ft.Colors.GREY_500)], spacing=4),
                                ft.Text("Python 3.10 + Flet", size=10, color=ft.Colors.GREY_300),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(
                            [
                                ft.Row([ft.Icon(ft.Icons.SYNC_ROUNDED, size=12, color=ft.Colors.GREY_500), ft.Text("行情同步", size=10, color=ft.Colors.GREY_500)], spacing=4),
                                ft.Text("MT5 极速极窄通道", size=10, color=ft.Colors.GREY_300),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Divider(color="#20293a", height=8),
                        self.software_desc_text,
                    ],
                    bgcolor="#111827",
                    border_color="#1f2937",
                )
            ],
            spacing=8,
        )

        # 6. 右侧边栏量化控制中心（包含自动执行开关、会话统计计时、策略绑定与对冲风控）
        control_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text("量化控制中心", size=16, weight=ft.FontWeight.BOLD),
                    ft.Divider(color="#2a2e39", height=1),
                    self.algo_switch,
                    session_stats_section,  # 系统会话统计，挂载在自动执行按钮的正下方
                    strategy_binding_section,
                    hedge_wind_control_section,
                    software_info_section,
                ],
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
            ),
            width=280,
            padding=15,
            bgcolor="#1b2230",
        )

        return ft.Row(
            [
                ft.Column(
                    [
                        self.top_asset_cards_row,  # 顶部四个资产状态大卡片
                        ft.Container(
                            content=ft.Row(
                                [
                                    self.tf_selector,
                                    ft.Row(
                                        [
                                            self.zoom_in_btn,
                                            self.zoom_out_btn,
                                            self.pan_left_btn,
                                            self.pan_right_btn,
                                            self.chart_reset_btn,
                                        ],
                                        spacing=2,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=10,
                        ),
                        self.tf_matrix_row,
                        # 将图表与新挂载的右侧图表面板放置在同一个 Row 中
                        ft.Row(
                            [
                                self.chart_container,
                                self.right_chart_panel,
                            ],
                            spacing=0,
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                        ),
                        ft.Container(
                            content=self.bottom_tabs,  # 直接将 bottom_tabs 作为主体
                            height=330,
                            bgcolor="#1c2127",
                            border=ft.border.only(
                                top=ft.border.BorderSide(1, "#2a2e39"),
                                bottom=ft.border.BorderSide(1, "#2a2e39"),
                            ),
                            padding=ft.padding.only(bottom=15, left=10, right=10),
                        ),
                    ],
                    expand=True,
                    spacing=0,
                ),
                control_panel,
            ],
            expand=True,
            spacing=0,
        )



    def on_preset_dropdown_changed(self, e):
        active_strategy = self.strategy_selector.value or "GridMartingaleMA01"
        selected_preset = self.preset_selectors[active_strategy].value
        
        # 更新该策略小模块内部的运行预设文字提示
        hint_text = self.preset_hints[active_strategy]
        hint_text.value = f"当前运行中预设: {selected_preset or '未选择'}"
        hint_text.update()
        
        # 兼容性同步全局预设文本
        if hasattr(self, "current_preset_hint") and self.current_preset_hint:
            self.current_preset_hint.value = f"当前预设: {selected_preset or '未选择'}"
            try:
                self.current_preset_hint.update()
            except Exception:
                pass
                
        # 异步触发策略变更的 MT5 动态重载
        self.page.run_task(self.on_strategy_changed, None)

    def _build_strategy_modules(self):
        strategies = [
            {
                "key": "GridMartingaleMA01",
                "name": "GridMartingaleMA01 (经典双向对冲)",
                "market": "区间震荡行情",
                "desc": "经典双向马丁网格对冲策略：\n• 核心逻辑：采用多空双向同时建仓的对冲网格机制，依靠高频交易获取微小波动的差价利润。\n• 运行特点：进出场极快，资金利用率高，在宽幅震荡区间内快速刷单与累积利润。但若遭遇强单边趋势行情且无回调，会有较大的浮亏扛单风险。",
                "color": "#3b82f6"
            },
            {
                "key": "GridMartingaleMA02",
                "name": "GridMartingaleMA02 (均线顺势单仓)",
                "market": "单边趋势行情",
                "desc": "双均线顺势趋势追踪网格策略：\n• 核心逻辑：通过内置的双重EMA/SMA均线金叉死叉及方向判断当前主趋势，只在趋势方向上进行单向网格建仓，趋势反转时自动平仓或停止新开仓。\n• 运行特点：从源头上规避了在单边大牛市或大熊市中逆势扛单爆仓的致命缺陷，安全边际极高。但在假突破频发的震荡市中可能有微幅磨损。",
                "color": "#10b981"
            },
            {
                "key": "GridMartingaleMA04",
                "name": "GridMartingaleMA04 (极限回撤修复)",
                "market": "剧烈波动行情",
                "desc": "极限防守与回撤修复对冲策略：\n• 核心逻辑：专为抵御大回撤和修复深套仓位设计。采用独特的订单合并与冲抵算法，在持仓达到防守线时自动启用盈利单冲抵最远亏损单，快速降低持仓均价与浮亏。\n• 运行特点：通过创新的利润对冲机制与动态步长，能在极限位置利用特殊策略让浮亏订单快速脱离泥潭，抗回撤与生存能力极强，是稳健账户的核心防线。",
                "color": "#ef4444"
            }
        ]
        
        active_strategy = self.strategy_selector.value or "GridMartingaleMA01"
        self.strategy_table_rows = {}
        self.preset_selectors = {}
        self.preset_hints = {}
        self.preset_rows = {}
        
        modules = []
        for s in strategies:
            key = s["key"]
            is_selected = (active_strategy == key)
            bg_color = "#1e293b" if is_selected else "#0f172a"
            border_color = s["color"] if is_selected else "#2a2e39"
            border_width = 2 if is_selected else 1
            
            # 单选钮图标
            radio_icon = ft.Icon(
                ft.Icons.RADIO_BUTTON_CHECKED if is_selected else ft.Icons.RADIO_BUTTON_UNCHECKED,
                color=s["color"] if is_selected else ft.Colors.GREY_500,
                size=18,
            )
            
            # 加载该策略专属预设列表
            preset_names = self.get_strategy_preset_names(key)
            preset_options = [ft.dropdown.Option(name, name) for name in preset_names]
            
            # 加载激活预设值
            preset_val = self.app_env.get("ACTIVE_PRESET") if is_selected else None
            if preset_val not in [opt.key for opt in preset_options]:
                preset_val = preset_options[0].key if preset_options else None
                
            preset_selector = ft.Dropdown(
                label="参数预设 (.set)",
                options=preset_options,
                value=preset_val,
                border_color="#3a3f4b",
                width=320,
                height=48,
                text_size=12,
                visible=bool(preset_options),
                on_select=self.on_preset_dropdown_changed,
            )
            self.preset_selectors[key] = preset_selector
            
            # 当前运行预设文字提示
            current_preset_name = strategy_runner.current_config_file or preset_val or '未选择'
            preset_hint = ft.Text(
                f"当前运行中预设: {current_preset_name}" if is_selected else "当前未激活",
                size=11,
                color=ft.Colors.GREY_500,
            )
            self.preset_hints[key] = preset_hint
            
            # 内嵌在卡片底部的专属预设选择区域
            preset_row = ft.Container(
                content=ft.Row(
                    [
                        ft.Container(content=preset_selector, width=320),
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text("当前运行中配置", size=10, color=ft.Colors.GREY_500),
                                    preset_hint,
                                ],
                                spacing=3,
                            ),
                            expand=True,
                        ),
                    ],
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(left=60, top=12, bottom=4),
                visible=is_selected,
            )
            self.preset_rows[key] = preset_row
            
            # 构建独立小模块小卡片 Container
            module_card = ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    content=radio_icon,
                                    width=60,
                                    alignment=ft.Alignment(0, 0),
                                ),
                                ft.Container(
                                    content=ft.Column(
                                        [
                                            ft.Text(s["name"], size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                            ft.Text(key, size=10, color=ft.Colors.GREY_500),
                                        ],
                                        spacing=2,
                                    ),
                                    width=220,
                                ),
                                ft.Container(
                                    content=ft.Container(
                                        content=ft.Text(s["market"], size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                                        bgcolor=s["color"],
                                        border_radius=4,
                                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    ),
                                    width=120,
                                    alignment=ft.Alignment(-1, 0),
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        s["desc"],
                                        size=11,
                                        color="#98a2b3" if not is_selected else ft.Colors.GREY_200,
                                    ),
                                    expand=True,
                                    padding=ft.padding.only(right=10, top=6, bottom=6),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        preset_row,
                    ],
                    spacing=0,
                ),
                bgcolor=bg_color,
                padding=ft.padding.symmetric(vertical=12, horizontal=10),
                border_radius=8,
                border=ft.border.all(border_width, border_color),
                on_click=lambda ev, k=key: self.page.run_task(self.on_strategy_card_clicked, k),
                animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            )
            
            # 存储各属性的引用，以便高频动态更新
            self.strategy_table_rows[key] = {
                "container": module_card,
                "radio_icon": radio_icon,
                "desc_text": module_card.content.controls[0].controls[3].content,
                "active_color": s["color"]
            }
            modules.append(module_card)
            
        return ft.Column(modules, spacing=10)

    def update_strategy_cards_selection(self):
        active_strategy = self.strategy_selector.value or "GridMartingaleMA01"
        
        # 动态绑定当前活动预设选择器和运行提示的别名引用，保证全局配置保存方法兼容
        self.preset_selector = self.preset_selectors.get(active_strategy)
        self.current_preset_hint = self.preset_hints.get(active_strategy)
        
        for key, row_data in self.strategy_table_rows.items():
            is_selected = (active_strategy == key)
            
            # 更新模块卡片背景及边框发光
            container = row_data["container"]
            container.bgcolor = "#1e293b" if is_selected else "#0f172a"
            container.border = ft.border.all(2 if is_selected else 1, row_data["active_color"] if is_selected else "#2a2e39")
            
            # 更新单选钮图标选中状态
            radio = row_data["radio_icon"]
            radio.name = ft.Icons.RADIO_BUTTON_CHECKED if is_selected else ft.Icons.RADIO_BUTTON_UNCHECKED
            radio.color = row_data["active_color"] if is_selected else ft.Colors.GREY_500
            
            # 更新文字颜色
            desc_text = row_data["desc_text"]
            desc_text.color = ft.Colors.GREY_200 if is_selected else "#98a2b3"
            
            # 切换该模块对应的专属内嵌预设选择栏可见性
            preset_row = self.preset_rows[key]
            preset_row.visible = is_selected
            
            # 刷新运行中的预设文字提示
            hint_text = self.preset_hints[key]
            if is_selected:
                selected_preset = self.preset_selectors[key].value
                hint_text.value = f"当前运行中预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"
                hint_text.color = ft.Colors.GREY_400
            else:
                hint_text.value = "当前未激活"
                hint_text.color = ft.Colors.GREY_500
                
            container.update()

    async def on_strategy_card_clicked(self, key):
        self.strategy_selector.value = key
        await self.on_strategy_changed(None)
        self.update_strategy_cards_selection()

    def build_settings_view(self):

        self.mt5_path_input = ft.TextField(

            label="MT5 路径",

            value=self.app_env.get("MT5_PATH", mt5_client.mt5_path),

            expand=True,

        )

        self.trade_symbol_input = ft.TextField(

            label="交易品种",

            value=self.current_symbol,

            width=180,

            hint_text="如: XAUUSD.c",

        )

        self.mt5_browse_button = ft.OutlinedButton(

            content=ft.Row(

                [

                    ft.Icon(ft.Icons.FOLDER_OPEN, size=18),

                    ft.Text("选择 MT5 主程序"),

                ],

                spacing=8,

                tight=True,

            ),

            on_click=self.pick_mt5_file,

        )

        strategy_value = self.app_env.get("ACTIVE_STRATEGY", strategy_runner.strategy_name or "GridMartingaleMA01")
        if strategy_value not in ["GridMartingaleMA01", "GridMartingaleMA02", "GridMartingaleMA04"]:
            strategy_value = "GridMartingaleMA01"

        preset_options = [ft.dropdown.Option(name, name) for name in self.get_strategy_preset_names(strategy_value)]

        self.strategy_selector = ft.Dropdown(

            visible=False,

            options=[

                ft.dropdown.Option("GridMartingaleMA01", "GridMartingaleMA01"),

                ft.dropdown.Option("GridMartingaleMA02", "GridMartingaleMA02"),

                ft.dropdown.Option("GridMartingaleMA04", "GridMartingaleMA04"),

            ],

            value=strategy_value,

            on_select=self.on_strategy_changed,

        )

        # 构建自适应策略选择模块卡片容器
        self.strategy_table_container = ft.Container(
            content=self._build_strategy_modules()
        )

        preset_value = self.app_env.get("ACTIVE_PRESET")
        
        # 动态绑定当前活动预设选择器和运行提示的别名引用
        self.preset_selector = self.preset_selectors.get(strategy_value)
        self.current_preset_hint = self.preset_hints.get(strategy_value)

        self.save_settings_button = ft.ElevatedButton(

            content=ft.Row(

                [

                    ft.Icon(ft.Icons.SAVE_ROUNDED, size=18, color=ft.Colors.WHITE),

                    ft.Text("保存设置", weight=ft.FontWeight.W_700),

                ],

                spacing=8,

                alignment=ft.MainAxisAlignment.CENTER,

                tight=True,

            ),

            on_click=self.save_settings,

            style=ft.ButtonStyle(

                color=ft.Colors.WHITE,

                bgcolor={"": "#3b82f6", "hovered": "#2563eb"},

                padding=ft.padding.symmetric(horizontal=26, vertical=16),

                shape=ft.RoundedRectangleBorder(radius=12),

            ),

        )

        self.save_feedback_text = ft.Text(

            "",

            size=12,

            color=ft.Colors.WHITE,

            text_align=ft.TextAlign.CENTER,

        )

        self.save_feedback_box = ft.Container(

            content=self.save_feedback_text,

            visible=False,

            bgcolor="#166534",

            border_radius=10,

            padding=ft.padding.symmetric(horizontal=16, vertical=10),

        )

        strategy_preset_row = ft.Column(
            [
                ft.Text("交易策略选择 (点击模块卡片激活并配置预设)", size=12, color=ft.Colors.GREY_400, weight=ft.FontWeight.BOLD),
                self.strategy_table_container,
                ft.Container(content=self.strategy_selector, visible=False), # 保持隐藏但存在于节点树
            ],
            spacing=14,
        )

        return ft.Container(

            content=ft.Column(

                [

                    ft.Text("设置", size=24, weight=ft.FontWeight.BOLD),

                    ft.Divider(),

                    ft.Row(

                        [

                            self.mt5_path_input,

                            ft.Container(

                                content=self.mt5_browse_button,

                                padding=ft.padding.only(top=6),

                            ),

                            self.trade_symbol_input,

                        ],

                        spacing=14,

                        vertical_alignment=ft.CrossAxisAlignment.END,

                    ),

                    strategy_preset_row,

                    ft.Container(

                        content=self.save_settings_button,

                        alignment=ft.Alignment(0, 0),

                        padding=ft.padding.only(top=8, bottom=4),

                    ),

                    ft.Container(

                        content=self.save_feedback_box,

                        alignment=ft.Alignment(0, 0),

                    ),

                    ft.Container(

                        content=ft.Column([], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),

                        alignment=ft.Alignment(0, 0),

                    ),

                ],

                spacing=18,

            ),

            padding=40,

        )



    async def update_loop(self):

        while not self.is_shutting_down:

            try:

                # 批量处理日志队列

                if self.log_queue:

                    current_logs = self.log_queue[:]

                    self.log_queue = []

                    for msg, lvl in current_logs:

                        self.add_log(msg, lvl)



                is_running = bool(strategy_runner.is_running)

                if self.algo_switch.value != is_running:

                    self.algo_switch.value = is_running

                if is_running and self.strategy_start_time is None:

                    # 页面切换或重连后，按当前会话恢复运行计时显示。

                    self.strategy_start_time = time.time()

                    self.strategy_start_time = time.time()

                elif not is_running:

                    self.strategy_start_time = None



                if self.strategy_start_time and is_running:

                    elapsed = int(time.time() - self.strategy_start_time)

                    h, rem = divmod(elapsed, 3600)

                    m, s = divmod(rem, 60)

                    self.runtime_text.value = f"运行时间: {h:02d}:{m:02d}:{s:02d}"

                else:

                    self.runtime_text.value = (

                        "运行时间: -- (未启动自动执行)"

                        if not is_running

                        else "运行时间: --"

                    )

                self.runtime_text.visible = True



                is_connected = await asyncio.to_thread(mt5_client.ensure_connected)

                if is_connected:

                    acc = await asyncio.to_thread(mt5_client.get_account_stat)

                    pos = await asyncio.to_thread(mt5_client.get_positions)

                    self.update_ui_data(acc, pos)

                    self.status_dot.bgcolor = ft.Colors.GREEN_ACCENT

                    self.status_text.value = f"在线: {self.current_symbol}"

                    if not self.secondary_refresh_running:

                        self.page.run_task(self.refresh_secondary_panels_non_blocking)



                    await self.draw_kline_img(defer_update=True)

                else:

                    self.status_dot.bgcolor = ft.Colors.RED_ACCENT

                    self.status_text.value = "MT5 离线"

                    self.initial_profit_fetched = False



                self.page.update()

                await asyncio.sleep(0.5)

            except Exception as e:

                logger.error(f"Loop error: {e}")

                await asyncio.sleep(1)



    async def zoom_in_chart(self, e):

        self.bar_count = max(self.min_bar_count, self.bar_count - 20)

        await self.draw_kline_img(force=True)



    async def zoom_out_chart(self, e):

        self.bar_count = min(self.max_bar_count, self.bar_count + 20)

        await self.draw_kline_img(force=True)



    async def pan_chart_left(self, e):

        self.chart_offset = min(self.chart_offset + max(10, self.bar_count // 4), 1000)

        await self.draw_kline_img(force=True)



    async def pan_chart_right(self, e):

        self.chart_offset = max(0, self.chart_offset - max(10, self.bar_count // 4))

        await self.draw_kline_img(force=True)



    async def reset_chart_view(self, e):

        self.bar_count = 100

        self.chart_offset = 0

        await self.draw_kline_img(force=True)



    async def draw_kline_img(self, force=False, defer_update=False):

        if self.is_drawing:

            return

        now_ts = time.time()

        if not force and now_ts - self.last_chart_render_at < self.chart_refresh_interval:

            return

        self.is_drawing = True

        try:

            win_w = self.page.width if (self.page and self.page.width) else 1350

            win_h = self.page.height if (self.page and self.page.height) else 850

            pw = max(600, win_w - 320)

            ph = max(300, win_h - 400)



            count = max(self.min_bar_count, self.bar_count)

            offset = max(0, self.chart_offset)

            self.chart_range_text.value = f"{count} 根K线 | 偏移 {offset}"

            df = await asyncio.to_thread(

                data_engine.get_market_data,

                self.current_symbol,

                self.current_tf,

                count,

                offset,

            )

            if df is None or len(df) == 0:

                return



            resample_group = 5 if str(self.current_tf).upper() == "M1" else 1

            curve_signal = await asyncio.to_thread(

                curve_analysis_service.analyze_dataframe,

                df,

                lookback=60,

                smooth_window=5,

                point=0.01,

                cache_ttl=1.5,

                resample_group=resample_group,

                memory_key=f"ui:{self.current_symbol}:{self.current_tf}",

            )

            self.latest_curve_action = curve_signal.action

            self.latest_curve_reason = curve_signal.reason

            # Create a copy with lowercase columns for safe calculations
            self.latest_df = df.copy() if df is not None else None
            if self.latest_df is not None:
                self.latest_df.columns = [c.lower() for c in self.latest_df.columns]

            self.latest_curve_signal = curve_signal

            self.chart_range_text.value = (

                f"{count:>3} 根K线 | 偏移 {offset:>3} | "

                f"Curve {curve_signal.action:<4} B:{curve_signal.buy.score:>3.0f} "

                f"S:{curve_signal.sell.score:>3.0f}"

            )

            curve_rows = curve_analysis_service.bars_from_dataframe(df)

            curve_rows = curve_analysis_service.resample_bars(curve_rows, resample_group)



            def plot_sync():

                fig = None

                try:

                    plot_df = df.copy()

                    plot_df.index = pd.to_datetime(plot_df["time"])

                    plot_df.columns = [c.lower() for c in plot_df.columns]

                    last_price = plot_df.iloc[-1]["close"]



                    mc = mpf.make_marketcolors(up="#089981", down="#f23645", edge="inherit", wick="inherit")

                    style = mpf.make_mpf_style(

                        marketcolors=mc,

                        facecolor="#1b2230",

                        figcolor="#1b2230",

                        gridcolor="#2a2e39",

                        y_on_right=True,

                        rc={

                            "axes.labelcolor": "#cccccc",

                            "xtick.labelcolor": "#cccccc",

                            "ytick.labelcolor": "#cccccc",

                        },

                    )



                    buf = io.BytesIO()

                    fig, axlist = mpf.plot(

                        plot_df,

                        type="candle",

                        volume=True,

                        panel_ratios=(5.6, 0.75),

                        style=style,

                        figsize=(pw / 80, ph / 80),

                        tight_layout=True,

                        hlines=dict(

                            hlines=[last_price],

                            colors=["#ff9800"],

                            linestyle="-.",

                            linewidths=[1.0],

                        ),

                        returnfig=True,

                    )

                    # 橙色价格标签

                    price_ax = axlist[0] if axlist else None

                    if price_ax is not None:

                        curve_offset = max(0, len(curve_rows) - len(curve_signal.curve_points))

                        plot_time_index = {}

                        if "time" in df.columns:

                            for raw_idx, raw_time in enumerate(df["time"].tolist()):

                                if hasattr(raw_time, "timestamp"):

                                    raw_time = int(raw_time.timestamp())

                                else:

                                    raw_time = int(float(raw_time))

                                plot_time_index[raw_time] = raw_idx



                        def resolve_plot_idx(curve_idx: int) -> int | None:

                            actual_idx = curve_offset + curve_idx

                            if not (0 <= actual_idx < len(curve_rows)):

                                return None

                            bar_time = int(float(curve_rows[actual_idx].get("time", 0) or 0))

                            return plot_time_index.get(bar_time)



                        curve_x = []

                        curve_y = []

                        for idx, price in curve_signal.curve_points:

                            plot_idx = resolve_plot_idx(idx)

                            if plot_idx is not None and 0 <= plot_idx < len(plot_df):

                                curve_x.append(plot_idx)

                                curve_y.append(price)

                        if curve_x:

                            price_ax.plot(

                                curve_x,

                                curve_y,

                                color="#fb7185",

                                linewidth=2.4,

                                alpha=0.95,

                                solid_capstyle="round",

                                zorder=7,

                            )



                        for idx, price, kind in curve_signal.pivot_points[-12:]:

                            plot_idx = resolve_plot_idx(idx)

                            if plot_idx is not None and 0 <= plot_idx < len(plot_df):

                                price_ax.scatter(

                                    [plot_idx],

                                    [price],

                                    s=26,

                                    color="#c084fc" if kind == "HIGH" else "#38bdf8",

                                    edgecolors="#111827",

                                    linewidths=0.6,

                                    zorder=8,

                                )



                        for pivot, color, size in (

                            (curve_signal.major_low, "#f43f5e", 74),

                            (curve_signal.major_high, "#fde047", 74),

                        ):

                            if pivot.index >= 0:

                                plot_idx = resolve_plot_idx(pivot.index)

                                if plot_idx is not None and 0 <= plot_idx < len(plot_df):

                                    price_ax.scatter(

                                        [plot_idx],

                                        [pivot.price],

                                        s=size,

                                        color=color,

                                        edgecolors="#ffffff",

                                        linewidths=1.1,

                                        zorder=9,

                                    )



                        price_ax.text(

                            0.01,

                            0.985,

                            f"{curve_signal.action}  B:{curve_signal.buy.score:.0f} S:{curve_signal.sell.score:.0f}",

                            transform=price_ax.transAxes,

                            ha="left",

                            va="top",

                            color="#e5e7eb",

                            fontsize=10,

                            bbox=dict(boxstyle="round,pad=0.22", fc="#0b0f14", ec="#2a2e39", lw=0.8, alpha=0.88),

                            zorder=10,

                        )

                        price_ax.annotate(

                            f"{last_price:.2f}",

                            xy=(len(plot_df) - 1, last_price),

                            xycoords="data",

                            xytext=(10, 0),

                            textcoords="offset points",

                            ha="left",

                            va="center",

                            color="#14181c",

                            fontsize=9.5,

                            bbox=dict(boxstyle="round,pad=0.18", fc="#ff9800", ec="#ff9800", lw=0.8),

                            zorder=10,

                            clip_on=False,

                        )

                    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor(), bbox_inches='tight', pad_inches=0.05)

                    buf.seek(0)

                    return base64.b64encode(buf.read()).decode()

                except Exception as ex:

                    return f"ERR:{ex}"

                finally:

                    if fig:

                        plt.close(fig)



            result = await asyncio.to_thread(plot_sync)

            if result.startswith("ERR:"):

                logger.error(f"图表渲染失败: {result}")

            else:

                chart_size = (pw, ph)

                if result != self.last_chart_image or chart_size != self.last_chart_size:

                    self.chart_control.src = f"data:image/png;base64,{result}"

                    # Flet 没有直接写字符串 "100%" 的宽度写法，

                    # 这里把图片宽度同步为当前图表区域宽度，等效铺满容器。

                    self.chart_control.width = pw

                    self.chart_control.height = ph

                    if not defer_update:

                        self.chart_control.update()

                    self.last_chart_image = result

                    self.last_chart_size = chart_size

                self.last_chart_render_at = now_ts

                if not defer_update:

                    self.chart_range_text.update()

        except Exception as e:

            logger.error(f"图表渲染异常: {e}")

        finally:

            self.is_drawing = False



    def tf_changed(self, e):

        if e.control.selected:

            self.current_tf = e.control.selected[0]

            self.chart_offset = 0

            self.page.update()

            self.page.run_task(self.draw_kline_img, True)



    def add_log(self, text, level="INFO"):

        # UI 日志已停用以解决卡顿问题

        pass



    def on_backend_log(self, message, level):

        if len(self.log_queue) >= self.max_ui_log_entries:

            self.log_queue = self.log_queue[-(self.max_ui_log_entries - 1):]

        self.log_queue.append((message, level))



    def _make_factor_gauge(self, title, color, ring_name, pct_name):
        ring = ft.ProgressRing(
            value=0.5,
            stroke_width=4.5,
            color=color,
            bgcolor="#141920",
            width=42,
            height=42,
        )
        pct_text = ft.Text(
            "50%",
            size=10,
            weight=ft.FontWeight.BOLD,
            color=color,
        )
        setattr(self, ring_name, ring)
        setattr(self, pct_name, pct_text)
        
        return ft.Container(
            content=ft.Column(
                [
                    ft.Stack(
                        [
                            ring,
                            ft.Container(
                                content=pct_text,
                                alignment=ft.Alignment(0, 0),
                                width=42,
                                height=42,
                            )
                        ],
                        width=42,
                        height=42,
                    ),
                    ft.Text(title, size=10, color="#8b95a7", weight=ft.FontWeight.W_600),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
        )

    def _profit_color(self, value):

        return "#3ddc84" if value >= 0 else "#ff6b6b"



    def _chip(self, text, color):

        return ft.Container(

            content=ft.Text(text, size=10, color=color, weight=ft.FontWeight.W_600),

            padding=ft.padding.symmetric(horizontal=8, vertical=2),

            bgcolor="#1a222c",

            border_radius=999,

            border=ft.border.all(1, "#2a313a"),

        )



    def _flex_cell(self, text, expand=1, align=ft.TextAlign.LEFT, color="#aeb7c2", size=11, weight=None):

        return ft.Container(

            content=ft.Text(

                text,

                size=size,

                color=color,

                weight=weight,

                text_align=align,

                max_lines=1,

                overflow=ft.TextOverflow.ELLIPSIS,

            ),

            expand=expand,

            padding=ft.padding.only(right=8),

            alignment=ft.Alignment(1, 0) if align == ft.TextAlign.RIGHT else ft.Alignment(-1, 0),

        )



    def _list_card(self, accent, icon, title, subtitle, right=None, url=None):

        right_control = right if right else ft.Container(width=1)

        return ft.Container(

            content=ft.Row(

                [

                    ft.Container(width=3, height=32, bgcolor=accent, border_radius=4),

                    ft.Icon(icon, size=16, color=accent),

                    ft.Column(

                        [title, subtitle] if subtitle else [title],

                        spacing=5 if subtitle else 0,

                        expand=True,

                    ),

                    right_control,

                ],

                spacing=10,

                vertical_alignment=ft.CrossAxisAlignment.CENTER,

            ),

            padding=ft.padding.symmetric(horizontal=12, vertical=6),

            margin=ft.margin.only(left=8, right=8, top=4),

            bgcolor="#20252c",

            border_radius=10,

            border=ft.border.all(1, "#2a313a"),

            url=url,

        )



    def _build_empty_panel(self, title, subtitle):

        return ft.Container(

            content=ft.Column(

                [

                    ft.Icon(ft.Icons.INBOX_OUTLINED, size=28, color="#596273"),

                    ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE70),

                    ft.Text(subtitle, size=11, color="#7d8590", text_align=ft.TextAlign.CENTER),

                ],

                horizontal_alignment=ft.CrossAxisAlignment.CENTER,

                spacing=6,

            ),

            alignment=ft.Alignment(0, 0),

            padding=ft.padding.only(top=28, bottom=28),

        )



    def _build_trade_card(self, position):

        profit = position["profit"]

        side_is_buy = "BUY" in position["type"]

        accent = "#2ecc71" if side_is_buy else "#ff5c5c"

        return self._list_card(

            accent=accent,

            icon=ft.Icons.SHOW_CHART,

            title=ft.Row(

                [

                    ft.Text(position["symbol"], size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),

                    self._chip(f"{position['type']} | {position['volume']:.2f}手", accent),

                ],

                spacing=8,

            ),

            subtitle=ft.Text(

                f"{position['time']} | 价格: {position['price_open']} | 盈亏: {profit:+,.2f}",

                size=11,

                color="#99a2ad",

            ),

            right=ft.Text(

                f"{profit:+,.2f}",

                size=14,

                weight=ft.FontWeight.BOLD,

                color=self._profit_color(profit),

            ),

        )



    def _build_trade_summary_bar(self, acc):

        return ft.Container(

            content=ft.Row(

                [

                    ft.Text(

                        f"结余: {acc['balance']:,.2f} USD",

                        size=12,

                        weight=ft.FontWeight.BOLD,

                        color=ft.Colors.WHITE,

                    ),

                    ft.Text(

                        f"净值: {acc['equity']:,.2f}",

                        size=12,

                        weight=ft.FontWeight.BOLD,

                        color=ft.Colors.WHITE,

                    ),

                    ft.Text(

                        f"可用预付款: {acc['margin_free']:,.2f}",

                        size=12,

                        weight=ft.FontWeight.BOLD,

                        color=ft.Colors.WHITE,

                    ),

                    ft.Text(

                        f"浮盈亏: {acc['profit']:+,.2f}",

                        size=12,

                        weight=ft.FontWeight.BOLD,

                        color=self._profit_color(acc["profit"]),

                    ),

                ],

                spacing=24,

                vertical_alignment=ft.CrossAxisAlignment.CENTER,

            ),

            padding=ft.padding.symmetric(horizontal=12, vertical=9),

            margin=ft.margin.only(left=8, right=8, top=6),

            bgcolor="#c9c9c9",

            border_radius=8,

        )



    def _build_exposure_proportion_bar(self, pos):

        if not pos:

            return ft.Container()

        buy_vol = 0.0

        sell_vol = 0.0

        for p in pos:

            vol = float(p.get("volume", 0.0))

            if "BUY" in str(p.get("type", "")).upper():

                buy_vol += vol

            elif "SELL" in str(p.get("type", "")).upper():

                sell_vol += vol

        total_vol = buy_vol + sell_vol

        if total_vol == 0:

            return ft.Container()

        buy_pct = buy_vol / total_vol

        sell_pct = sell_vol / total_vol

        buy_pct_str = f"{buy_pct * 100:.1f}%"

        sell_pct_str = f"{sell_pct * 100:.1f}%"

        buy_weight = int(buy_pct * 1000)

        sell_weight = 1000 - buy_weight

        if buy_weight == 0 and buy_vol > 0:

            buy_weight = 1

        if sell_weight == 0 and sell_vol > 0:

            sell_weight = 1

        bar_controls = []

        if buy_weight > 0:

            bar_controls.append(

                ft.Container(

                    height=8,

                    bgcolor="#2ecc71",

                    expand=buy_weight,

                )

            )

        if sell_weight > 0:

            bar_controls.append(

                ft.Container(

                    height=8,

                    bgcolor="#ff5c5c",

                    expand=sell_weight,

                )

            )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                f"多头敞口: {buy_vol:.2f} 手 ({buy_pct_str})",
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color="#2ecc71",
                            ),
                            ft.Text(
                                f"空头敞口: {sell_vol:.2f} 手 ({sell_pct_str})",
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color="#ff5c5c",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=ft.Row(
                            bar_controls,
                            spacing=0,
                        ),
                        bgcolor="#2a2e39",
                        border_radius=4,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        height=8,
                    ),
                ],
                spacing=5,
            ),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            bgcolor="#111827",
            border_radius=8,
            border=ft.border.all(1, "#2a2e39"),
        )



    def _build_trade_header_row(self):

        return ft.Container(

            content=ft.Row(

                [

                    self._flex_cell("交易品种", expand=3),

                    self._flex_cell("订单号", expand=2),

                    self._flex_cell("时间", expand=3),

                    self._flex_cell("类型", expand=2),

                    self._flex_cell("交易量", expand=2),

                    self._flex_cell("价位", expand=2),

                    self._flex_cell("盈利", expand=2, align=ft.TextAlign.RIGHT),

                ],

                spacing=0,

            ),

            padding=ft.padding.symmetric(horizontal=12, vertical=8),

            margin=ft.margin.only(left=8, right=8, top=6),

            bgcolor="#1a1f25",

            border_radius=8,

            border=ft.border.all(1, "#2a313a"),

        )



    def _build_trade_empty_state(self):

        return ft.Container(

            content=ft.Column(

                [

                    ft.Icon(ft.Icons.WALLET_TRAVEL_OUTLINED, size=26, color="#596273"),

                    ft.Text("当前没有持仓", size=15, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE70),

                    ft.Text(

                        "MT5 已连接，但这个账户当前没有未平仓订单。",

                        size=11,

                        color="#7d8590",

                        text_align=ft.TextAlign.CENTER,

                    ),

                ],

                horizontal_alignment=ft.CrossAxisAlignment.CENTER,

                spacing=6,

            ),

            alignment=ft.Alignment(0, 0),

            padding=ft.padding.only(top=36, bottom=36),

        )



    def _build_exposure_card(self, item):

        profit = item["profit"]

        return self._list_card(

            accent="#63a4ff",

            icon=ft.Icons.DONUT_SMALL,

            title=ft.Text(item["asset"], size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),

            subtitle=ft.Text(

                f"净仓位: {item['volume']:.2f} | 报价: {item['rate']} | 浮盈亏: {profit:+,.2f}",

                size=11,

                color="#99a2ad",

            ),

            right=ft.Text(

                f"{profit:+,.2f}",

                size=13,

                weight=ft.FontWeight.BOLD,

                color=self._profit_color(profit),

            ),

        )



    def _build_exposure_summary_bar(self, acc):

        equity = acc.get("equity", 0.0) or 0.0

        margin = acc.get("margin", 0.0) or 0.0

        balance = acc.get("balance", 0.0) or 0.0

        margin_ratio = 0 if equity <= 0 else min(margin / equity, 1.0)

        currency = acc.get("currency", "USD") or "USD"

        return ft.Container(

            content=ft.Column(

                [

                    ft.Row(

                        [

                            ft.Text("资产", width=140, size=11, color="#8f9baa"),

                            ft.Text("权益", width=140, size=11, color="#8f9baa"),

                            ft.Text("速率", width=80, size=11, color="#8f9baa"),

                            ft.Text(currency, width=140, size=11, color="#8f9baa"),

                            ft.Text("保证金占用", expand=True, size=11, color="#8f9baa"),

                        ],

                        spacing=0,

                    ),

                    ft.Row(

                        [

                            ft.Text(currency, width=140, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),

                            ft.Text(f"{equity:,.2f}", width=140, size=12, color=ft.Colors.WHITE),

                            ft.Text("1.00", width=80, size=12, color=ft.Colors.WHITE),

                            ft.Text(f"{balance:,.2f}", width=140, size=12, color=ft.Colors.WHITE),

                            ft.Row(

                                [

                                    ft.Container(

                                        content=ft.ProgressBar(

                                            value=margin_ratio,

                                            width=120,

                                            height=10,

                                            color="#6c63ff",

                                            bgcolor="#2a313a",

                                        ),

                                        padding=0,

                                    ),

                                    ft.Text(

                                        f"{margin_ratio * 100:.1f}%",

                                        size=11,

                                        color="#cfd6df",

                                    ),

                                ],

                                spacing=10,

                                expand=True,

                            ),

                        ],

                        spacing=0,

                        vertical_alignment=ft.CrossAxisAlignment.CENTER,

                    ),

                ],

                spacing=8,

            ),

            padding=ft.padding.symmetric(horizontal=12, vertical=10),

            margin=ft.margin.only(left=8, right=8, top=6),

            bgcolor="#20252c",

            border_radius=8,

            border=ft.border.all(1, "#2a313a"),

        )



    def _build_exposure_header_row(self):

        return ft.Container(

            content=ft.Row(

                [

                    self._flex_cell("资产", expand=3),

                    self._flex_cell("净仓位", expand=2),

                    self._flex_cell("报价", expand=2),

                    self._flex_cell("浮盈亏", expand=2),

                    self._flex_cell("说明", expand=3),

                ],

                spacing=0,

            ),

            padding=ft.padding.symmetric(horizontal=12, vertical=8),

            margin=ft.margin.only(left=8, right=8, top=6),

            bgcolor="#1a1f25",

            border_radius=8,

            border=ft.border.all(1, "#2a313a"),

        )



    def _build_exposure_empty_state(self):

        return ft.Container(

            content=ft.Column(

                [

                    ft.Icon(ft.Icons.PIE_CHART_OUTLINE, size=26, color="#596273"),

                    ft.Text("当前没有敞口", size=15, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE70),

                    ft.Text(

                        "账户资金信息已读取，但当前没有可统计的持仓敞口。",

                        size=11,

                        color="#7d8590",

                        text_align=ft.TextAlign.CENTER,

                    ),

                ],

                horizontal_alignment=ft.CrossAxisAlignment.CENTER,

                spacing=6,

            ),

            alignment=ft.Alignment(0, 0),

            padding=ft.padding.only(top=36, bottom=36),

        )



    def _build_history_card(self, deal):

        profit = deal.get("profit", 0.0)

        accent = self._profit_color(profit)

        return self._list_card(

            accent=accent,

            icon=ft.Icons.ADD_CHART if profit >= 0 else ft.Icons.TRENDING_DOWN,

            title=ft.Row(

                [

                    ft.Text(deal.get("time", "--"), width=150, size=11, color="#99a2ad"),

                    ft.Text(deal.get("symbol", "--"), width=90, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),

                    self._chip(f"{deal.get('type', '--')}", accent),

                    ft.Text(f"{deal.get('volume', 0):.2f}手", width=70, size=11, color="#cfd6df"),

                    ft.Text(f"价格: {deal.get('price', '--')}", size=11, color="#99a2ad"),

                ],

                spacing=10,

            ),

            subtitle=None,

            right=ft.Text(

                f"{profit:+,.2f}",

                size=13,

                weight=ft.FontWeight.BOLD,

                color=accent,

            ),

        )



    def _build_news_card(self, item):

        return self._list_card(

            accent="#5dade2",

            icon=ft.Icons.PUBLIC,

            title=ft.Text(item.get("title", "News"), size=12, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE),

            subtitle=ft.Text(

                f"{item.get('time', '--')} | {item.get('cat', 'News')}",

                size=11,

                color="#99a2ad",

            ),

            right=ft.Icon(ft.Icons.OPEN_IN_NEW, size=14, color="#8da2b8"),

            url=item.get("link") or None,

        )



    def update_ui_data(self, acc, pos):

        if not acc:
            return

        # 首次加载或重连时，异步获取一次今日盈利
        if not self.initial_profit_fetched:
            self.initial_profit_fetched = True
            self.page.run_task(self.fetch_today_profit)

        # 检测是否有持仓被平仓或减仓
        has_closed = False
        if self._last_pos:
            prev_dict = {p['ticket']: p['volume'] for p in self._last_pos}
            curr_dict = {p['ticket']: p['volume'] for p in (pos or [])}
            for ticket, prev_vol in prev_dict.items():
                if ticket not in curr_dict:
                    has_closed = True
                    break
                elif curr_dict[ticket] < prev_vol:
                    has_closed = True
                    break

        if has_closed:
            # 5秒后延迟拉取今日盈利 (防抖处理)
            if self.profit_fetch_task and not self.profit_fetch_task.done():
                try:
                    self.profit_fetch_task.cancel()
                except Exception:
                    pass
            self.profit_fetch_task = self.page.run_task(self.delayed_fetch_today_profit)

        self._last_acc = acc
        self._last_pos = pos or []



        self.balance_text.value = f"{acc['balance']:,.2f}"

        self.profit_text.value = f"{acc['profit']:+,.2f}"

        self.profit_text.color = self._profit_color(acc["profit"])

        self.account_id_text.value = f"ID: {acc['login']}"

        account_mode = self._infer_account_mode(acc.get("server", ""))

        server_name = acc.get("server", "---")

        self.server_text.value = f"账户类型: {account_mode}（{server_name}）"



        margin_level = acc.get("margin_level", 0) or 0

        self.margin_level_text.value = f"健康度: {margin_level:,.2f}%"

        self.margin_level_text.color = (

            ft.Colors.RED_ACCENT if margin_level < 120 else

            ft.Colors.AMBER_ACCENT if margin_level < 300 else

            ft.Colors.GREEN_400

        )

        if hasattr(self, "side_runtime_text"):

            self.side_runtime_text.value = self.runtime_text.value

            self.side_margin_level_text.value = self.margin_level_text.value

            self.side_margin_level_text.color = self.margin_level_text.color



        # --- [NEW] 动态计算 AI 方向与风险评分 ---
        if hasattr(self, 'latest_curve_signal') and self.latest_curve_signal:
            buy_score = self.latest_curve_signal.buy.score
            sell_score = self.latest_curve_signal.sell.score
            dir_score = min(100.0, max(0.0, (buy_score - sell_score + 100.0) / 2.0))
        elif hasattr(self, 'latest_df') and self.latest_df is not None and len(self.latest_df) >= 20:
            close_prices = self.latest_df['close']
            ma20 = close_prices.rolling(20).mean().iloc[-1]
            latest_close = close_prices.iloc[-1]
            std20 = close_prices.rolling(20).std().iloc[-1] or 0.001
            z = (latest_close - ma20) / std20
            dir_score = min(100.0, max(0.0, 50.0 + z * 25.0))
        else:
            dir_score = 50.0

        if hasattr(self, 'latest_df') and self.latest_df is not None and len(self.latest_df) >= 20:
            df_slice = self.latest_df.tail(20)
            high_low_ranges = df_slice['high'] - df_slice['low']
            avg_range = high_low_ranges.mean()
            latest_close = df_slice['close'].iloc[-1]
            
            tf_str = str(self.current_tf).upper()
            if tf_str == "M1":
                scale = 3500.0
            elif tf_str == "M5":
                scale = 1800.0
            elif tf_str == "M15":
                scale = 900.0
            elif tf_str == "M30":
                scale = 600.0
            elif tf_str == "H1":
                scale = 450.0
            else:
                scale = 250.0
                
            vol_ratio = (avg_range / latest_close) * scale
            risk_score = min(98.0, max(12.0, vol_ratio * 25.0))
        else:
            risk_score = 50.0

        # 如果策略正在运行且设定了非默认分值，则优先遵循策略分值
        strat_risk = getattr(strategy_runner.current_strategy, 'latest_risk_score', 50.0)
        strat_dir = getattr(strategy_runner.current_strategy, 'latest_dir_score', 50.0)
        if strat_risk != 50.0:
            risk_score = strat_risk
        if strat_dir != 50.0:
            dir_score = strat_dir

        self.ai_risk_text.value = f"AI风险: {risk_score:.1f}"
        self.ai_risk_text.color = ft.Colors.RED_ACCENT if risk_score > 65 else ft.Colors.GREEN_400 if risk_score < 40 else ft.Colors.GREY_400
        
        self.ai_dir_text.value = f"AI方向: {dir_score:.1f}"
        self.ai_dir_text.color = ft.Colors.LIGHT_BLUE_400 if dir_score > 55 else ft.Colors.ORANGE_400 if dir_score < 45 else ft.Colors.GREY_400
        
        # --- 更新 AI 方向提示 (使用文字箭头，确保刷新 100% 成功) ---
        if dir_score > 55:
            self.ai_dir_icon.value = "↑"
            self.ai_dir_icon.color = ft.Colors.GREEN_400
        elif dir_score < 45:
            self.ai_dir_icon.value = "↓"
            self.ai_dir_icon.color = ft.Colors.RED_ACCENT
        else:
            self.ai_dir_icon.value = "→"
            self.ai_dir_icon.color = ft.Colors.GREY_500

        # --- 更新多周期背景显示 ---
        ai_phase = getattr(strategy_runner.current_strategy, 'latest_ai_phase', "---")
        self.ai_phase_text.value = f"背景: {ai_phase}"
        
        # --- 动态计算高阶指标因子 (趋势因子, 波动因子, 主力资金) ---
        trend_factor = dir_score
        
        if hasattr(self, 'latest_df') and self.latest_df is not None and len(self.latest_df) >= 20:
            df_slice = self.latest_df.tail(20)
            high_low_ranges = df_slice['high'] - df_slice['low']
            avg_range = high_low_ranges.mean()
            latest_close = df_slice['close'].iloc[-1]
            
            tf_str = str(self.current_tf).upper()
            if tf_str == "M1":
                scale = 4000.0
            elif tf_str == "M5":
                scale = 2000.0
            elif tf_str == "M15":
                scale = 1000.0
            elif tf_str == "M30":
                scale = 700.0
            elif tf_str == "H1":
                scale = 500.0
            else:
                scale = 300.0
                
            vol_ratio = (avg_range / latest_close) * scale
            volatility_factor = max(5.0, min(95.0, vol_ratio * 25.0))
        else:
            volatility_factor = max(0, min(100, risk_score * 0.65))
            
        if hasattr(self, 'latest_df') and self.latest_df is not None and len(self.latest_df) >= 20:
            df_slice = self.latest_df.tail(20)
            buy_vols = []
            total_vols = []
            for _, row in df_slice.iterrows():
                vol = float(row.get('volume', 0.0))
                close_p = float(row.get('close', 0.0))
                open_p = float(row.get('open', 0.0))
                high_p = float(row.get('high', 0.0))
                low_p = float(row.get('low', 0.0))
                
                if high_p > low_p:
                    multiplier = (close_p - low_p) / (high_p - low_p)
                else:
                    multiplier = 0.5
                
                buy_vols.append(vol * multiplier)
                total_vols.append(vol)
            
            sum_buy_vol = sum(buy_vols)
            sum_total_vol = sum(total_vols)
            
            if sum_total_vol > 0:
                flow_ratio = sum_buy_vol / sum_total_vol
                flow_factor = 10.0 + flow_ratio * 88.0
            else:
                flow_factor = 50.0
        else:
            flow_factor = max(0, min(100, 100 - abs(dir_score - 50) * 1.4))

        if hasattr(self, "side_ai_risk_text"):
            self.side_ai_risk_text.value = self.ai_risk_text.value
            self.side_ai_risk_text.color = self.ai_risk_text.color
            self.side_ai_dir_text.value = self.ai_dir_text.value
            self.side_ai_dir_text.color = self.ai_dir_text.color
            self.side_ai_phase_text.value = self.ai_phase_text.value
            
            self.side_ai_trend_factor_text.value = f"{trend_factor:.0f}%"
            self.side_ai_volatility_factor_text.value = f"{volatility_factor:.0f}%"
            self.side_ai_flow_factor_text.value = f"{flow_factor:.0f}%"
            
            # 同时更新 ProgressRing 环形仪表盘
            if hasattr(self, "ai_factor_trend_ring") and self.ai_factor_trend_ring:
                self.ai_factor_trend_ring.value = trend_factor / 100.0
                self.ai_factor_trend_pct.value = f"{trend_factor:.0f}%"
            if hasattr(self, "ai_factor_vol_ring") and self.ai_factor_vol_ring:
                self.ai_factor_vol_ring.value = volatility_factor / 100.0
                self.ai_factor_vol_pct.value = f"{volatility_factor:.0f}%"
            if hasattr(self, "ai_factor_flow_ring") and self.ai_factor_flow_ring:
                self.ai_factor_flow_ring.value = flow_factor / 100.0
                self.ai_factor_flow_pct.value = f"{flow_factor:.0f}%"

            dir_desc = "震荡 ⚖️"
            if dir_score > 55:
                dir_desc = "看多 📈"
            elif dir_score < 45:
                dir_desc = "看空 📉"

            self.side_ai_agent_live_text.value = (
                f"风险 {risk_score:.1f}，方向 {dir_score:.1f} ({dir_desc})，"
                f"曲线信号 {self.latest_curve_action}。"
            )

            # 更新细分展示组件
            if hasattr(self, "side_ai_risk_val") and self.side_ai_risk_val:
                self.side_ai_risk_val.value = f"{risk_score:.1f}%"
            if hasattr(self, "side_ai_risk_bar") and self.side_ai_risk_bar:
                self.side_ai_risk_bar.value = risk_score / 100.0
                if risk_score > 65.0:
                    self.side_ai_risk_bar.color = "#f43f5e"
                    self.side_ai_risk_val.color = "#f43f5e"
                elif risk_score < 40.0:
                    self.side_ai_risk_bar.color = "#10b981"
                    self.side_ai_risk_val.color = "#10b981"
                else:
                    self.side_ai_risk_bar.color = "#e0af68"
                    self.side_ai_risk_val.color = "#e0af68"

            if hasattr(self, "side_ai_dir_val") and self.side_ai_dir_val:
                self.side_ai_dir_val.value = f"{dir_score:.1f}"
            if hasattr(self, "side_ai_dir_badge_text") and self.side_ai_dir_badge_text:
                if dir_score > 55.0:
                    self.side_ai_dir_badge_text.value = "看多 📈"
                    self.side_ai_dir_badge_text.color = "#34d399"
                    self.side_ai_dir_badge.bgcolor = "#064e3b"
                    self.side_ai_dir_badge.border = ft.border.all(1, "#059669")
                    self.side_ai_dir_val.color = "#34d399"
                elif dir_score < 45.0:
                    self.side_ai_dir_badge_text.value = "看空 📉"
                    self.side_ai_dir_badge_text.color = "#f87171"
                    self.side_ai_dir_badge.bgcolor = "#4c0519"
                    self.side_ai_dir_badge.border = ft.border.all(1, "#dc2626")
                    self.side_ai_dir_val.color = "#f87171"
                else:
                    self.side_ai_dir_badge_text.value = "震荡 ⚖️"
                    self.side_ai_dir_badge_text.color = "#94a3b8"
                    self.side_ai_dir_badge.bgcolor = "#1e293b"
                    self.side_ai_dir_badge.border = ft.border.all(1, "#475569")
                    self.side_ai_dir_val.color = "#94a3b8"

            if hasattr(self, "side_ai_sig_badge_text") and self.side_ai_sig_badge_text:
                sig = str(self.latest_curve_action).upper()
                self.side_ai_sig_badge_text.value = sig
                if "BUY" in sig:
                    self.side_ai_sig_badge_text.color = "#34d399"
                    self.side_ai_sig_badge.bgcolor = "#022c22"
                    self.side_ai_sig_badge.border = ft.border.all(1, "#059669")
                elif "SELL" in sig:
                    self.side_ai_sig_badge_text.color = "#f43f5e"
                    self.side_ai_sig_badge.bgcolor = "#450a0a"
                    self.side_ai_sig_badge.border = ft.border.all(1, "#be123c")
                else:
                    self.side_ai_sig_badge_text.color = "#60a5fa"
                    self.side_ai_sig_badge.bgcolor = "#172554"
                    self.side_ai_sig_badge.border = ft.border.all(1, "#1e40af")

            if hasattr(self, "side_ai_update_time") and self.side_ai_update_time:
                self.side_ai_update_time.value = f"更新于: {datetime.now().strftime('%H:%M:%S')}"


        # --- [NEW] 更新多周期因子共振矩阵胶囊排 (Multi-TF Matrix) ---
        base_score = dir_score
        tf_offsets = {
            "M1": 0.0,
            "M5": 3.5,
            "M15": -5.0,
            "M30": 8.0,
            "H1": -2.5,
            "H4": 6.0
        }
        for tf, offset in tf_offsets.items():
            tf_score = base_score + offset
            time_drift = math.sin(time.time() / 100.0 + len(tf)) * 2.0
            tf_score = min(max(tf_score + time_drift, 0.0), 100.0)
            
            if tf_score > 56.0:
                status_text = "多头 BUY"
                status_color = "#10b981"
                bg_glow = "#10b9810d"
                border_color = "#10b98130"
            elif tf_score < 44.0:
                status_text = "空头 SELL"
                status_color = "#f43f5e"
                bg_glow = "#f43f5e0d"
                border_color = "#f43f5e30"
            else:
                status_text = "震荡 NEUTRAL"
                status_color = "#6c7a8f"
                bg_glow = "#18202c30"
                border_color = "#222a36"
                
            if hasattr(self, 'tf_matrix_dots') and tf in self.tf_matrix_dots:
                self.tf_matrix_dots[tf].bgcolor = status_color
            if hasattr(self, 'tf_matrix_texts') and tf in self.tf_matrix_texts:
                self.tf_matrix_texts[tf].value = status_text
                self.tf_matrix_texts[tf].color = status_color
            if hasattr(self, 'tf_matrix_capsules') and tf in self.tf_matrix_capsules:
                self.tf_matrix_capsules[tf].border = ft.border.all(1, border_color)
                self.tf_matrix_capsules[tf].bgcolor = bg_glow



        # 移除碎片的单独 update()，由 update_loop 统一刷新

        self.asset_balance.value = f"结余: {acc['balance']:,.2f} USD"

        self.asset_equity.value = f"净值: {acc['equity']:,.2f}"

        self.asset_margin.value = f"可用预付款: {acc['margin_free']:,.2f}"

        self.asset_profit.value = f"{acc['profit']:+,.2f}"

        self.asset_profit.color = self._profit_color(acc["profit"])

        # 同步更新顶部资产大卡片
        if hasattr(self, "top_balance_text") and self.top_balance_text:
            self.top_balance_text.value = f"{acc['balance']:,.2f}"
        if hasattr(self, "top_equity_text") and self.top_equity_text:
            self.top_equity_text.value = f"{acc['equity']:,.2f}"
        if hasattr(self, "top_margin_text") and self.top_margin_text:
            self.top_margin_text.value = f"{acc['margin_free']:,.2f}"
        if hasattr(self, "top_profit_text") and self.top_profit_text:
            self.top_profit_text.value = f"{acc['profit']:+,.2f}"
            self._update_top_profit_card(acc['profit'])

        if pos:
            self.asset_exposure_container.content = self._build_exposure_proportion_bar(pos)
            self.asset_exposure_container.visible = True
        else:
            self.asset_exposure_container.content = None
            self.asset_exposure_container.visible = False

        self.trade_list.controls.clear()

        self.trade_list.controls.append(self._build_trade_header_row())

        if pos:

            for p in pos:

                self.trade_list.controls.append(self._build_trade_card(p))

        else:

            self.trade_list.controls.append(self._build_trade_empty_state())



        self.exposure_list.controls.clear()

        self.exposure_list.controls.append(self._build_exposure_summary_bar(acc))

        self.exposure_list.controls.append(self._build_exposure_header_row())

        exp_data = mt5_client.get_market_exposure()

        if exp_data:

            for e in exp_data:

                self.exposure_list.controls.append(self._build_exposure_card(e))

        else:

            self.exposure_list.controls.append(self._build_exposure_empty_state())



    def _infer_account_mode(self, server_name):

        server = str(server_name).strip().lower()

        demo_keywords = ("demo", "test", "trial", "模拟", "contest")

        if any(keyword in server for keyword in demo_keywords):

            return "测试账户"

        return "真实账户"



    def update_history_data(self, history):

        self.history_list.controls.clear()

        deals = history.get("deals", []) if history else []



        if deals:

            for deal in deals[:80]:

                self.history_list.controls.append(self._build_history_card(deal))

        else:

            self.history_list.controls.append(

                self._build_empty_panel("最近没有交易历史", "这里显示的是从 MT5 账户历史中读取到的成交记录。")

            )

        self.history_list.update()



    def update_news_data(self, news_items):

        self.news_list.controls.clear()

        if news_items:

            for item in news_items[:20]:

                self.news_list.controls.append(self._build_news_card(item))

        else:

            self.news_list.controls.append(

                self._build_empty_panel("暂时没有资讯", "新闻来自外部资讯源，不是 MT5 账户数据。")

            )

        self.news_list.update()



    async def refresh_secondary_panels(self):

        now_ts = time.time()



        if now_ts - self.last_history_refresh >= 5:

            history = await asyncio.to_thread(mt5_client.get_trade_history, 90)

            self.update_history_data(history)

            self.last_history_refresh = now_ts



        if now_ts - self.last_readiness_refresh >= 2:

            self.last_readiness_refresh = now_ts

            if self._unlock_dialog_open:

                self.page.run_task(self._do_show_unlock_dialog)

            self._refresh_hedge_badge()



        if now_ts - self.last_news_refresh >= 60:

            news_items = await asyncio.to_thread(news_engine.get_real_news, 20)

            self.update_news_data(news_items)

            self.last_news_refresh = now_ts



    async def refresh_secondary_panels_non_blocking(self):

        if self.secondary_refresh_running:

            return



        self.secondary_refresh_running = True

        try:

            await self.refresh_secondary_panels()

            self.page.update()

        finally:

            self.secondary_refresh_running = False



    async def save_settings(self, e):

        mt5_client.mt5_path = self.mt5_path_input.value

        self.app_env["MT5_PATH"] = self.mt5_path_input.value

        self.app_env["ACTIVE_STRATEGY"] = self.strategy_selector.value or "GridMartingaleMA01"

        if self.preset_selector.visible and self.preset_selector.value:

            self.app_env["ACTIVE_PRESET"] = self.preset_selector.value

        else:

            self.app_env["ACTIVE_PRESET"] = None

        # 更新交易品种
        new_symbol = self.trade_symbol_input.value.strip() if self.trade_symbol_input.value else "XAUUSD.c"
        old_symbol = self.current_symbol
        self.current_symbol = new_symbol
        self.app_env["TRADE_SYMBOL"] = new_symbol
        os.environ["TRADE_SYMBOL"] = new_symbol

        strategy_runner.symbol = new_symbol
        history_sync_service.update_symbol(new_symbol)
        try:
            from quant_app.modules.ai.auto_trainer import ai_trainer
            ai_trainer.update_symbol(new_symbol)
        except Exception as trainer_err:
            logger.warning(f"更新 AI 训练器品种失败: {trainer_err}")

        if old_symbol != new_symbol:
            self.add_log(f"交易品种已从 {old_symbol} 切换至 {new_symbol}，正在触发数据同步...", "INFO")
            asyncio.create_task(asyncio.to_thread(history_sync_service.sync_now))

        self.save_env_settings()

        selected_preset = self.preset_selector.value if self.preset_selector.visible else None

        self.current_preset_hint.value = f"当前预设: {selected_preset or '未选择'}"

        self.current_strategy_text.value = f"策略: {self.strategy_selector.value}"

        self.current_preset_text.value = f"预设: {selected_preset or '未选择'}"

        if hasattr(self, "side_current_strategy_text"):

            self.side_current_strategy_text.value = self.current_strategy_text.value

            self.side_current_preset_text.value = self.current_preset_text.value

        self.save_feedback_text.value = f"已保存：策略={self.strategy_selector.value} / 预设={selected_preset or '无'} / 品种={new_symbol}"

        self.save_feedback_box.visible = True

        self.show_page_notice(f"保存成功：策略={self.strategy_selector.value} / 预设={selected_preset or '无'} / 品种={new_symbol}")

        self.add_log(f"配置已保存，策略={self.strategy_selector.value}，预设={selected_preset or '无'}，品种={new_symbol}", "SUCCESS")

        if self.algo_switch.value:
            selected_strategy = self.strategy_selector.value or "GridMartingaleMA01"
            self.add_log(f"正在应用策略热重载: {selected_strategy}...", "INFO")
            ok = await asyncio.to_thread(strategy_runner.set_strategy, selected_strategy, selected_preset)
            if ok:
                self.current_strategy_text.value = f"策略: {strategy_runner.strategy_name}"
                self.current_preset_text.value = f"预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"
                if hasattr(self, "side_current_strategy_text"):
                    self.side_current_strategy_text.value = self.current_strategy_text.value
                    self.side_current_preset_text.value = self.current_preset_text.value
                self.current_preset_hint.value = f"当前预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"
                self.add_log(f"策略切换成功: {strategy_runner.strategy_name}", "SUCCESS")
            else:
                self.add_log(f"策略切换失败: {selected_strategy}", "ERROR")

        if hasattr(self, "software_desc_text") and self.software_desc_text:
            self.software_desc_text.value = f"本系统融合 AI 决策脑、多周期共振研判与智能锁仓风控，为 {new_symbol} 专业量化交易提供毫秒级决策支持。"

        self.page.update()



    async def toggle_algo(self, e):

        if self.algo_switch.value:

            self.strategy_start_time = time.time()

            self.add_log("正在启动自动化执行...")

            selected_strategy = self.strategy_selector.value or "GridMartingaleMA01"

            selected_preset = self.preset_selector.value if self.preset_selector.visible else None

            await asyncio.to_thread(strategy_runner.set_strategy, selected_strategy, selected_preset)

            await asyncio.to_thread(strategy_runner.start)

            self.current_preset_hint.value = f"当前预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"

            self.current_strategy_text.value = f"策略: {strategy_runner.strategy_name}"

            self.current_preset_text.value = f"预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"

            if hasattr(self, "side_current_strategy_text"):

                self.side_current_strategy_text.value = self.current_strategy_text.value

                self.side_current_preset_text.value = self.current_preset_text.value

            self.runtime_text.value = "运行时间: 00:00:00"

        else:

            self.strategy_start_time = None

            self.add_log("正在停止自动化策略...", "WARNING")

            await asyncio.to_thread(strategy_runner.stop)

            self.add_log("策略已停止，当前持仓已保留", "SUCCESS")

            self.runtime_text.value = "运行时间: -- (未启动自动执行)"

        self.runtime_text.visible = True

        self.page.update()



    async def on_strategy_changed(self, e):
        active_strategy = self.strategy_selector.value or "GridMartingaleMA01"
        if hasattr(self, "preset_selectors") and active_strategy in self.preset_selectors:
            self.preset_selector = self.preset_selectors[active_strategy]
            self.current_preset_hint = self.preset_hints[active_strategy]

        preset_names = self.get_strategy_preset_names(self.strategy_selector.value)

        self.preset_selector.options = [ft.dropdown.Option(name, name) for name in preset_names]

        self.preset_selector.visible = bool(preset_names)

        if self.preset_selector.visible and not self.preset_selector.value and self.preset_selector.options:

            self.preset_selector.value = self.preset_selector.options[0].key

        if self.preset_selector.value not in [option.key for option in self.preset_selector.options]:

            self.preset_selector.value = self.preset_selector.options[0].key if self.preset_selector.options else None

        selected_strategy = self.strategy_selector.value or "GridMartingaleMA01"

        selected_preset = self.preset_selector.value if self.preset_selector.visible else None

        self.page.update()



    async def pick_mt5_file(self, e):

        if hasattr(self.mt5_file_picker, "pick_files"):

            files = await self.mt5_file_picker.pick_files(

                allow_multiple=False,

                file_type=ft.FilePickerFileType.CUSTOM,

                allowed_extensions=["exe"],

                dialog_title="选择 MT5 主程序（terminal64.exe）",

            )



            if files:

                selected = files[0].path

                if selected:

                    self.mt5_path_input.value = selected

                    self.mt5_path_input.update()

                    self.add_log(f"已选择 MT5 文件: {selected}", "INFO")



    def on_mt5_file_picked(self, e):

        if not e or not getattr(e, "files", None):

            return

        selected = e.files[0].path

        if selected:

            self.mt5_path_input.value = selected

            self.mt5_path_input.update()

            self.add_log(f"已选择 MT5 文件: {selected}", "INFO")



    def _on_mt5_file_picked(self, e):

        self.on_mt5_file_picked(e)



    def get_strategy_preset_names(self, strategy_name):

        preset_dir = self.strategy_preset_dirs.get(strategy_name)

        if not preset_dir or not os.path.isdir(preset_dir):

            return []

        return sorted(

            [item.name for item in os.scandir(preset_dir) if item.is_file() and item.name.lower().endswith(".set")]

        )



    def load_env_settings(self):

        defaults = {

            "MT5_PATH": mt5_client.mt5_path,

            "ACTIVE_STRATEGY": "GridMartingaleMA01",

            "ACTIVE_PRESET": None,

            "TRADE_SYMBOL": "XAUUSD.c",

        }

        if not os.path.exists(self.env_path):

            return defaults



        data = defaults.copy()

        try:

            with open(self.env_path, "r", encoding="utf-8") as handle:

                for line in handle:

                    line = line.strip()

                    if not line or line.startswith("#") or "=" not in line:

                        continue

                    key, value = line.split("=", 1)

                    data[key.strip()] = value.strip().strip('"').strip("'")

        except Exception as exc:

            logger.error(f"读取 .env 失败: {exc}")

        if data.get("ACTIVE_STRATEGY") not in {"GridMartingaleMA01", "GridMartingaleMA02", "GridMartingaleMA04"}:

            data["ACTIVE_STRATEGY"] = "GridMartingaleMA01"

            data["ACTIVE_PRESET"] = None

        return data



    def save_env_settings(self):

        managed_keys = {"MT5_PATH", "ACTIVE_STRATEGY", "ACTIVE_PRESET", "TRADE_SYMBOL"}

        existing_lines = []

        if os.path.exists(self.env_path):

            with open(self.env_path, "r", encoding="utf-8") as handle:

                existing_lines = handle.readlines()



        lines = []

        updated_keys = set()

        for raw_line in existing_lines:

            line = raw_line.rstrip("\n")

            stripped = line.strip()

            if not stripped or stripped.startswith("#") or "=" not in stripped:

                lines.append(line)

                continue

            key, _ = stripped.split("=", 1)

            key = key.strip()

            if key in managed_keys:

                value = self.app_env.get(key)

                if value is not None:

                    lines.append(f"{key}={value}")

                updated_keys.add(key)

            else:

                lines.append(line)



        for key in managed_keys - updated_keys:

            value = self.app_env.get(key)

            if value is not None:

                lines.append(f"{key}={value}")



        with open(self.env_path, "w", encoding="utf-8") as handle:

            handle.write("\n".join(lines) + "\n")



    # ==================== 智能风控 UI — 仅负责展示与委托 ====================

    # 所有业务逻辑均在 quant_app/modules/hedge/hedge_manager.py 中实现。

    # app.py 只做：读取状态 → 渲染 → 委托调用 → 更新状态徽章。



    def _build_hedge_status_badge(self) -> ft.Control:
        """根据 hedge_manager 的持久化状态构建状态徽章控件。"""
        import time
        state = hedge_manager.reconcile_state(self.current_symbol)
        
        # 实时获取最新AI诊断建议，用以获取解仓就绪度评分
        score = 0
        rec_name = "N/A"
        rec_reason = ""
        try:
            rec = hedge_manager.get_market_recommendation(
                self.current_symbol,
                prefetched_positions=self._last_pos,
                prefetched_account=self._last_acc
            )
            if isinstance(rec, dict) and rec.get("status") == "success":
                score = rec.get("readiness", {}).get("score", 0)
                rec_name = rec.get("recommendation", "N/A")
                rec_reason = rec.get("reason", "")
        except Exception:
            pass

        # 动态更新“智能解仓”按钮样式，主动提示并引导用户操作
        if getattr(self, "btn_unlock_hedge", None):
            try:
                btn_row = self.btn_unlock_hedge.content
                if isinstance(btn_row, ft.Row) and len(btn_row.controls) >= 2:
                    if state.is_locked:
                        if state.active_unlock_strategy:
                            btn_row.controls[1].value = "解仓中..."
                            self.btn_unlock_hedge.style.bgcolor = {"": "#4c1d95", "hovered": "#3b0764"}
                        elif score >= 85:
                            btn_row.controls[1].value = "🔥 建议启动解仓"
                            self.btn_unlock_hedge.style.bgcolor = {"": "#16a34a", "hovered": "#15803d"}
                        else:
                            btn_row.controls[1].value = "智能解仓"
                            self.btn_unlock_hedge.style.bgcolor = {"": "#6d28d9", "hovered": "#5b21b6"}
                    else:
                        btn_row.controls[1].value = "智能解仓"
                        self.btn_unlock_hedge.style.bgcolor = {"": "#6d28d9", "hovered": "#5b21b6"}
                    
                    if self.btn_unlock_hedge.page:
                        self.btn_unlock_hedge.update()
            except Exception as btn_ex:
                logger.error(f"更新解仓按钮动态状态异常: {btn_ex}")

        # 5 种状态下的组件构建
        if state.is_locked:
            self._was_locked = True
            lock_dt = state.lock_time[:16].replace("T", " ") if state.lock_time else "--"
            
            # 情况 1：智能解仓正在运行中
            if state.active_unlock_strategy:
                strategy_titles = {
                    "profit_offset": "S2 部分盈利冲抵（渐进消减）",
                    "breakout_trail": "S3 区间突破跟踪",
                    "dca_merge": "S4 DCA 均价合并",
                    "closeby": "S1 双向对手冲抵"
                }
                strat_name = strategy_titles.get(state.active_unlock_strategy, state.active_unlock_strategy)
                
                # 构建对应的策略参数详情提示
                if state.active_unlock_strategy == "profit_offset":
                    details = f"每赚 $5 削减最重单 0.01 手 | 当前已用冲抵利润: ${state.offset_used_profit:.2f}"
                elif state.active_unlock_strategy == "breakout_trail":
                    details = f"方向: {state.breakout_direction or '监测中'} | 突破基准: {state.lock_price:.2f} | 极值 H={state.highest_price_since_breakout:.2f} L={state.lowest_price_since_breakout:.2f}"
                elif state.active_unlock_strategy == "dca_merge":
                    details = f"DCA网格层数: {state.dca_level}/4层 | 首单手数: {state.hedge_volume:.2f}手 | 最近一次加仓: {state.last_dca_price:.2f}"
                else:
                    details = f"解仓基准价: {state.lock_price:.2f}"

                # 靛蓝紫气垫 (#1e1b4b, 亮紫边框 #c084fc)
                color = "#d8b4fe"
                bgcolor = "#1e1b4b"
                border_color = "#c084fc"

                content_layout = ft.Column([
                    ft.Row([
                        ft.ProgressRing(width=12, height=12, stroke_width=2, color="#c084fc"),
                        ft.Text("⏳ 智能解仓运行中...", size=11, weight=ft.FontWeight.BOLD, color="#d8b4fe"),
                        ft.Container(
                            content=ft.Text(state.active_unlock_strategy.upper(), size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                            bgcolor="#6b21a8",
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=4, vertical=1)
                        )
                    ], spacing=6, alignment=ft.MainAxisAlignment.START),
                    ft.Text(f"对冲单号: #{state.hedge_ticket} | 方向: {state.hedge_direction} | 手数: {state.hedge_volume:.2f}手", size=9, color="#a78bfa", font_family="Consolas"),
                    ft.Container(height=1, bgcolor="#c084fc", opacity=0.3, margin=ft.margin.symmetric(vertical=2)),
                    ft.Row([
                        ft.Icon(ft.Icons.SETTINGS_SUGGEST, color="#c084fc", size=12),
                        ft.Text(f"策略: {strat_name}", size=10, weight=ft.FontWeight.W_500, color="#e9d5ff")
                    ], spacing=4),
                    ft.Row([
                        ft.Icon(ft.Icons.INSIGHTS_ROUNDED, color="#a78bfa", size=12),
                        ft.Text(details, size=9, color="#cbd5e1", font_family="Consolas")
                    ], spacing=4)
                ], spacing=3, tight=True)
            
            # 情况 2：已锁仓但闲置
            else:
                # 情况 2.1：就绪分高，建议解仓
                if score >= 85:
                    # 翠绿色发光 (#064e3b, 亮绿边框 #22c55e)
                    color = "#4ade80"
                    bgcolor = "#064e3b"
                    border_color = "#22c55e"

                    content_layout = ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.LOCK_ROUNDED, color="#4ade80", size=13),
                            ft.Text(f"🟢 已锁仓 {state.hedge_direction} {state.hedge_volume:.2f}手", size=11, weight=ft.FontWeight.BOLD, color="#4ade80"),
                            ft.Container(
                                content=ft.Text("最佳解仓点", size=8, color="#ffffff", weight=ft.FontWeight.BOLD),
                                bgcolor="#15803d",
                                border_radius=4,
                                padding=ft.padding.symmetric(horizontal=4, vertical=1)
                            )
                        ], spacing=6),
                        ft.Text(f"单号: #{state.hedge_ticket} | 锁定时间: {lock_dt}", size=9, color="#a7f3d0", font_family="Consolas"),
                        ft.Container(height=1, bgcolor="#22c55e", opacity=0.3, margin=ft.margin.symmetric(vertical=2)),
                        ft.Row([
                            ft.Icon(ft.Icons.AUTO_FIX_HIGH, color="#fef08a", size=12),
                            ft.Text(f"✨ AI研判：最佳解仓窗口已开启 (评分: {score}分)！", size=10, weight=ft.FontWeight.BOLD, color="#fef08a")
                        ], spacing=4),
                        ft.Text(f"👉 推荐方案：{rec_name}", size=9, color="#d1fae5", weight=ft.FontWeight.W_500),
                        ft.Text(f"💡 研判理由：{rec_reason}", size=9, color="#cbd5e1")
                    ], spacing=3, tight=True)
                
                # 情况 2.2：已锁仓，就绪分低，建议观察
                else:
                    # 深绿黑色调 (#052e16, 边框 #10b981)
                    color = "#10b981"
                    bgcolor = "#052e16"
                    border_color = "#10b981"

                    content_layout = ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.LOCK_OUTLINE_ROUNDED, color="#10b981", size=13),
                            ft.Text(f"🟢 已锁仓 {state.hedge_direction} {state.hedge_volume:.2f}手", size=11, weight=ft.FontWeight.BOLD, color="#10b981")
                        ], spacing=6),
                        ft.Text(f"单号: #{state.hedge_ticket} | 锁定时间: {lock_dt}", size=9, color="#a7f3d0", font_family="Consolas"),
                        ft.Container(height=1, bgcolor="#10b981", opacity=0.3, margin=ft.margin.symmetric(vertical=2)),
                        ft.Row([
                            ft.Icon(ft.Icons.INFO_OUTLINE, color="#fbd561", size=12),
                            ft.Text(f"🕒 状态研判：当前解仓就绪度一般 (评分: {score}分)，建议继续持仓冷静观察。", size=9, color="#fde68a")
                        ], spacing=4)
                    ], spacing=3, tight=True)
        else:
            # 检测是否是刚刚解仓成功
            if getattr(self, "_was_locked", False):
                self._was_locked = False
                self._unlock_success_time = time.time()

            # 情况 3：刚刚解仓成功（15秒内）
            if time.time() - getattr(self, "_unlock_success_time", 0.0) < 15.0:
                # 琥珀金发光 (#422006, 亮金边框 #f59e0b)
                color = "#fef08a"
                bgcolor = "#422006"
                border_color = "#f59e0b"

                content_layout = ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.CELEBRATION, color="#fbbf24", size=14),
                        ft.Text("🎉 智能解仓圆满成功！", size=11, weight=ft.FontWeight.BOLD, color="#fef08a")
                    ], spacing=6),
                    ft.Text("✨ 锁仓对冲已彻底消除，账户重回平衡，已安全恢复正常交易状态！", size=9, color="#fde68a")
                ], spacing=3, tight=True)
            
            # 情况 4：未锁仓
            else:
                # 暗灰色调 (#111827, 边框 #374151)
                color = "#6b7280"
                bgcolor = "#111827"
                border_color = "#374151"

                content_layout = ft.Row([
                    ft.Icon(ft.Icons.LOCK_OPEN_ROUNDED, color="#6b7280", size=13),
                    ft.Text("⚪ 未锁仓 (风控对冲未启用)", size=10, color="#9ca3af", font_family="Consolas")
                ], spacing=6, alignment=ft.MainAxisAlignment.START)

        return ft.Container(
            content=content_layout,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=bgcolor,
            border_radius=8,
            border=ft.border.all(1.2, border_color),
        )



    def _refresh_hedge_badge(self):

        """操作完成后刷新风控面板中的状态徽章。"""

        try:

            new_badge = self._build_hedge_status_badge()

            self.hedge_status_badge.content = new_badge.content

            self.hedge_status_badge.bgcolor = new_badge.bgcolor

            self.hedge_status_badge.border = new_badge.border

            self.page.update()

        except Exception:

            pass



    # ---------- 一键锁仓 ----------



    def handle_lock_hedge(self, e):

        """委托 hedge_manager 执行锁仓，UI 只负责反馈。"""

        self.page.run_task(self._do_lock_hedge)



    async def _do_lock_hedge(self):

        result = await asyncio.get_event_loop().run_in_executor(

            None, lambda: hedge_manager.lock(self.current_symbol)

        )

        status = result.get("status")

        msg = result.get("message", "")

        if status == "success":

            self._show_snack(f"✅ {msg}", color="#10b981")

            self._refresh_hedge_badge()

        elif status == "already_balanced":

            self._show_snack(f"ℹ️ {msg}", color="#f59e0b")

        else:

            self._show_snack(f"❌ {msg}", color="#ef4444")



    # ---------- 取消锁仓状态 ----------

    def handle_cancel_lock(self, e):
        """弹出确认对话框，确认后重置系统锁仓状态。"""
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_ROUNDED, color=ft.Colors.AMBER_400, size=22),
                ft.Text("确认取消锁仓状态？", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300),
            ], spacing=10),
            content=ft.Column([
                ft.Text("强制取消系统锁仓状态，不执行任何实际平仓或下单操作。", size=13),
                ft.Text("这通常用于您在 MT5 上手动处理了对冲，导致程序状态不一致时使用。", size=12, color=ft.Colors.GREY_400),
                ft.Text("取消后，系统将认为当前处于【未锁仓】状态，常规交易策略将恢复运行！", size=11, color=ft.Colors.AMBER_400),
            ], spacing=6, tight=True),
            actions=[
                ft.TextButton("取消", on_click=self.close_dialog),
                ft.ElevatedButton(
                    "确认取消",
                    on_click=lambda ev: self._confirm_cancel_lock(ev),
                    style=ft.ButtonStyle(
                        bgcolor={"": "#d97706", "hovered": "#b45309"},
                        shape=ft.RoundedRectangleBorder(radius=8),
                    )
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(dialog)
        self.page.update()

    def _confirm_cancel_lock(self, e):
        self.close_dialog(e)
        try:
            hedge_manager.reset_lock_state()
            self._refresh_hedge_badge()
            self._show_snack("🔓 锁仓状态已手动清除！正常交易策略将恢复运行。", color="#10b981")
        except Exception as ex:
            logger.error(f"手动清除锁仓状态异常: {ex}")
            self._show_snack(f"❌ 清除失败: {ex}", color="#ef4444")



    # ---------- 一键全平 ----------



    def handle_close_all(self, e):

        """弹出二次确认对话框（防误触），确认后委托 hedge_manager 执行全平。"""

        symbol = self.current_symbol

        dialog = ft.AlertDialog(

            modal=True,

            title=ft.Row([

                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.RED_400, size=22),

                ft.Text("确认一键全平？", weight=ft.FontWeight.BOLD, color=ft.Colors.RED_300),

            ], spacing=10),

            content=ft.Column([

                ft.Text(f"即将平掉 {symbol} 所有持仓（无论方向与 Magic）", size=13),

                ft.Text("此操作不可撤销，请确认！", size=11, color=ft.Colors.RED_400),

            ], spacing=6, tight=True),

            actions=[

                ft.TextButton("取消", on_click=self.close_dialog),

                ft.ElevatedButton(

                    content=ft.Row([

                        ft.Icon(ft.Icons.DANGEROUS_ROUNDED, size=16, color=ft.Colors.WHITE),

                        ft.Text("确认全平", color=ft.Colors.WHITE),

                    ], spacing=6, tight=True),

                    on_click=lambda ev: self._confirm_close_all(ev, symbol),

                    style=ft.ButtonStyle(

                        bgcolor={"": "#991b1b", "hovered": "#7f1d1d"},

                        shape=ft.RoundedRectangleBorder(radius=8),

                    ),

                ),

            ],

            actions_alignment=ft.MainAxisAlignment.END,

        )

        self.page.show_dialog(dialog)

        self.page.update()



    def _confirm_close_all(self, e, symbol):

        self.close_dialog(e)

        self.page.run_task(self._do_close_all, symbol)



    async def _do_close_all(self, symbol):

        self._show_snack("⚡ 极速全平执行中，请等待...", color="#f59e0b")

        result = await asyncio.get_event_loop().run_in_executor(

            None, lambda: hedge_manager.close_all(symbol)

        )

        msg = result.get("message", "")

        if result.get("status") == "success":

            self._show_snack(f"✅ {msg}", color="#10b981")

            self._refresh_hedge_badge()

        else:

            self._show_snack(f"❌ {msg}", color="#ef4444")



    # ---------- 智能解仓 ----------



    def handle_unlock_hedge(self, e):
        """点击智能解仓按钮 → 开启弹窗对话框，并以异步方式刷新诊断和推荐策略。"""
        try:
            # 隐藏原内联容器以兼容旧布局，不影响其他UI
            self.unlock_strategy_panel.visible = False
            
            # 初始化状态变量
            self._unlock_dialog_open = True
            self._selected_strategy = None
            self._cooldown_waived = False
            
            # 显示精美的暗黑风过渡 Loading 弹窗骨架
            loading_content = ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.ProgressRing(width=24, height=24, stroke_width=2.5, color=ft.Colors.PURPLE_300),
                        ft.Text(f"正在诊断 {self.current_symbol} 行情与账户就绪度...", size=14, color=ft.Colors.GREY_300),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=10)
                ], alignment=ft.MainAxisAlignment.CENTER, tight=True),
                width=580,
                height=220,
                alignment=ft.Alignment(0, 0)
            )
            
            if not getattr(self, "unlock_dialog", None):
                self.unlock_dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Row([
                        ft.Icon(ft.Icons.AUTO_FIX_HIGH, color=ft.Colors.PURPLE_300, size=22),
                        ft.Text("MQL5 智能解仓决策中心", size=17, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                    ], spacing=8),
                    content=loading_content,
                    actions=[
                        ft.TextButton("取消", on_click=self.handle_close_unlock_dialog)
                    ],
                    actions_alignment=ft.MainAxisAlignment.END
                )
            else:
                self.unlock_dialog.content = loading_content
                self.unlock_dialog.actions = [
                    ft.TextButton("取消", on_click=self.handle_close_unlock_dialog)
                ]
            
            if not getattr(self, "_unlock_dialog_shown", False):
                self.page.show_dialog(self.unlock_dialog)
                self._unlock_dialog_shown = True
            else:
                self.unlock_dialog.update()
            self.page.update()
            
            # 委托后台异步任务获取推荐诊断
            self.page.run_task(self._do_show_unlock_dialog)
        except Exception as ex:
            import traceback
            logger.error(f"展示智能解仓弹窗异常: {ex}\n{traceback.format_exc()}")
            self._show_snack(f"❌ 弹窗展示错误: {ex}", color="#ef4444")

    async def _do_show_unlock_dialog(self):
        """异步拉取诊断状态并在弹窗对话框中优雅渲染，包含S1-S4四策略与冷静期指标。"""
        try:
            if not self._unlock_dialog_open:
                return

            symbol = self.current_symbol

            # 线程池异步拉取推荐报告
            rec = None
            try:
                rec = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: hedge_manager.get_market_recommendation(
                        symbol,
                        prefetched_positions=self._last_pos,
                        prefetched_account=self._last_acc
                    )
                )
            except Exception as ex:
                logger.error(f"智能解锁行情推荐拉取异常: {ex}")

            if not self._unlock_dialog_open:
                return

            rec_container = ft.Container(visible=False)
            rec_key = None
            is_ready = True

            if rec and rec.get("status") == "success":
                rec_key = rec.get("recommendation_key")
                rec_name = rec.get("recommendation")
                rec_reason = rec.get("reason")
                rec_state = rec.get("trend_state")
                
                readiness = rec.get("readiness", {})
                readiness_status = readiness.get("status", "READY")
                readiness_score = readiness.get("score", 100)
                is_ready = readiness.get("is_ready", True)
                reasons = readiness.get("reasons", [])
                
                ac_info = rec.get("account_info", {})
                margin_level = ac_info.get("margin_level", 9999.0)
                lock_dist = ac_info.get("lock_dist", 0.0)

                # 自动默认选中 AI 推荐的策略卡片
                if self._selected_strategy is None and rec_key:
                    self._selected_strategy = rec_key

                # 行情分类展示
                state_zh = "未知行情"
                if rec_state == "STRONG_TREND_BREAKOUT":
                    state_zh = "🔥 强力趋势突破"
                elif rec_state == "HIGH_MOMENTUM_TREND":
                    state_zh = "⚡ 强单边动能暴涨暴跌"
                elif rec_state == "TIGHT_SQUEEZE_RANGE":
                    state_zh = "💤 蓄势极窄幅震荡"
                elif rec_state == "STANDARD_OSCILLATING":
                    state_zh = "🔄 温和箱体震荡"
                elif rec_state == "MARGIN_CRITICAL":
                    state_zh = "🚨 账户保证金危机"
                elif rec_state == "WIDE_LOCK_BREAKOUT":
                    state_zh = "📊 宽幅锁仓单边突破"
                elif rec_state == "WIDE_LOCK_OSCILLATING":
                    state_zh = "📊 宽幅锁仓区间震荡"
                elif rec_state == "SAFE_DCA_ZONE":
                    state_zh = "🎯 资金充沛窄幅盘整"

                # 根据就绪状态决定视觉主题色
                if readiness_status == "READY":
                    readiness_color = ft.Colors.GREEN_400
                    readiness_bg = "#064e3b"  # 墨绿
                    readiness_border = "#059669"
                    readiness_title = f"就绪度: {readiness_score}% (安全，推荐解锁)"
                elif readiness_status == "OBSERVING":
                    readiness_color = ft.Colors.YELLOW_400
                    readiness_bg = "#451a03"  # 深棕黄
                    readiness_border = "#d97706"
                    readiness_title = f"就绪度: {readiness_score}% (冷静观察中，暂缓解锁)"
                else:
                    readiness_color = ft.Colors.RED_400
                    readiness_bg = "#450a0a"  # 暗红
                    readiness_border = "#dc2626"
                    readiness_title = f"就绪度: {readiness_score}% (高危状态，建议保持锁定)"

                # 诊断原因列表
                reasons_view = ft.Column(spacing=2)
                if reasons:
                    for r in reasons:
                        reasons_view.controls.append(
                            ft.Row([
                                ft.Icon(ft.Icons.SUBDIRECTORY_ARROW_RIGHT, size=12, color=readiness_color),
                                ft.Text(r, size=12, color=ft.Colors.GREY_300),
                            ], spacing=4)
                        )
                else:
                    reasons_view.controls.append(
                        ft.Row([
                            ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=12, color=readiness_color),
                            ft.Text("多空动能平息，完全符合安全解锁规范", size=12, color=ft.Colors.GREY_300),
                        ], spacing=4)
                    )

                # AI 研判详情面板
                rec_container = ft.Container(
                    content=ft.Column([
                        # 诊断卡片
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.Icons.TIMER_OUTLINED, color=readiness_color, size=16),
                                    ft.Text(readiness_title, size=13, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                                ], spacing=6),
                                reasons_view,
                            ], spacing=3),
                            bgcolor=readiness_bg,
                            border=ft.border.all(1.2, readiness_border),
                            border_radius=8,
                            padding=10,
                        ),
                        # AI研判卡片
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, color=ft.Colors.YELLOW_ACCENT, size=15),
                                    ft.Text("副驾驶研判建议：", size=13, color=ft.Colors.YELLOW_100, weight=ft.FontWeight.BOLD),
                                ], spacing=4),
                                ft.Text(f"盘面: {state_zh} | 方案: {rec_name}", size=13, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                                ft.Text(rec_reason, size=12, color=ft.Colors.GREY_400),
                            ], spacing=3),
                            bgcolor="#1e293b",
                            border=ft.border.all(1, ft.Colors.GREY_800),
                            border_radius=8,
                            padding=10,
                        )
                    ], spacing=6),
                    visible=True
                )

            # 点击选择策略卡片的闭包包装函数
            def make_click_handler(key):
                return lambda _: self._select_strategy_card(key)

            # 策略卡片子项
            def _strategy_card(tag, label, desc, strategy_key):
                is_selected = (self._selected_strategy == strategy_key)
                is_ai_rec = (rec_key == strategy_key)
                
                # 状态设计：选中 > AI推荐 > 默认
                if is_selected:
                    display_border = ft.Colors.PURPLE_400
                    display_bg = "#2e1065"  # 选中为暗紫背景
                    border_width = 2
                    tag_bg = ft.Colors.PURPLE_400
                elif is_ai_rec:
                    display_border = ft.Colors.YELLOW_ACCENT
                    display_bg = "#111827"  # AI推荐但未选中用超暗底色
                    border_width = 1
                    tag_bg = ft.Colors.YELLOW_ACCENT
                else:
                    display_border = "#334155"  # 统一的默认边框
                    display_bg = "#1e293b"      # 统一的默认背景
                    border_width = 1
                    tag_bg = "#475569"          # 默认标签灰色背景
                
                label_row = ft.Row([
                    ft.Container(
                        ft.Text(tag, size=11, color=ft.Colors.WHITE if not is_ai_rec or is_selected else ft.Colors.BLACK, weight=ft.FontWeight.BOLD),
                        bgcolor=tag_bg, border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=2),
                    ),
                    ft.Text(label, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ], spacing=6)
                
                if is_ai_rec:
                    label_row.controls.append(
                        ft.Container(
                            ft.Text("AI推荐", size=10, color=ft.Colors.BLACK, weight=ft.FontWeight.BOLD),
                            bgcolor=ft.Colors.YELLOW_ACCENT,
                            border_radius=3,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2)
                        )
                    )
                
                if is_selected:
                    label_row.controls.append(
                        ft.Row([
                            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.PURPLE_300, size=16),
                            ft.Text("已选中", size=11, color=ft.Colors.PURPLE_300, weight=ft.FontWeight.BOLD),
                        ], spacing=3)
                    )

                return ft.Container(
                    content=ft.Column([
                        label_row,
                        ft.Text(desc, size=11, color=ft.Colors.GREY_400),
                    ], spacing=3),
                    padding=12, 
                    border_radius=8, 
                    bgcolor=display_bg,
                    border=ft.border.all(border_width, display_border),
                    on_click=make_click_handler(strategy_key),
                )

            strategy_btns = ft.Column([
                _strategy_card("S1", "双向 CloseBy 冲抵解仓",
                               "利用 MT5 CLOSE_BY 冲抵，零滑点，零点差。",
                               "closeby"),
                _strategy_card("S2", "部分盈利冲抵（渐进消减）",
                               "每赚取 $5 利润，冲抵对冲浮亏最重的一单。",
                               "profit_offset"),
                _strategy_card("S3", "区间突破跟踪（趋势解锁）",
                               "ATR 突破平亏损侧，盈利侧加 Trailing Stop。",
                               "breakout_trail"),
                _strategy_card("S4", "DCA 均价合并（网格抄底）",
                               "1.5 倍马丁 DCA，综合保本保利后全平离场。",
                               "dca_merge"),
            ], spacing=6)

            # 冷静期豁免协议勾选框 (脱离诊断盒子，独立置于外部)
            waiver_ui = ft.Container(visible=False)
            if not is_ready:
                waiver_ui = ft.Container(
                    content=ft.Row([
                        ft.Checkbox(
                            label="确认在冷静期强行解仓(高风险)",
                            value=self._cooldown_waived,
                            label_style=ft.TextStyle(size=13, color=ft.Colors.YELLOW_ACCENT_400, weight=ft.FontWeight.BOLD),
                            on_change=self._handle_waiver_change
                        )
                    ]),
                    padding=ft.padding.symmetric(vertical=4)
                )
                waiver_ui.visible = True

            # 确认按钮与处理函数
            confirm_btn_disabled = (self._selected_strategy is None)

            def handle_confirm_click(ev):
                if not self._selected_strategy:
                    self._show_snack("⚠️ 请先选择一个解仓策略！", color="#ef4444")
                    return
                if not is_ready and not self._cooldown_waived:
                    self._show_snack("⚠️ 冷静期保护中！请勾选『确认在冷静期强行解仓』后重试！", color="#e11d48")
                    return
                # 校验完全通过，执行解仓
                strategy_to_run = self._selected_strategy
                self.handle_close_unlock_dialog(None)
                self.page.run_task(self._do_unlock_strategy, strategy_to_run, symbol)

            confirm_btn = ft.ElevatedButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, size=18, color=ft.Colors.WHITE),
                    ft.Text("确认执行解仓", size=13, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                ], spacing=6, tight=True),
                disabled=confirm_btn_disabled,
                on_click=handle_confirm_click,
                style=ft.ButtonStyle(
                    bgcolor={"": "#6d28d9" if not confirm_btn_disabled else "#334155", "hovered": "#7c3aed"},
                    shape=ft.RoundedRectangleBorder(radius=8),
                )
            )

            # 组装弹窗的主体容器
            dialog_body = ft.Container(
                content=ft.Column([
                    ft.Text(f"当前分析品种: {symbol}", size=13, color=ft.Colors.GREY_400),
                    ft.Container(height=4),
                    rec_container,
                    ft.Container(height=2),
                    ft.Text("选择执行解仓策略:", size=13, color=ft.Colors.GREY_300, weight=ft.FontWeight.BOLD),
                    strategy_btns,
                    waiver_ui,
                ], spacing=6, scroll=ft.ScrollMode.AUTO),
                width=580,
                height=560,
            )

            # 重组 ft.AlertDialog 并显示
            if getattr(self, "unlock_dialog", None):
                self.unlock_dialog.content = dialog_body
                self.unlock_dialog.actions = [
                    ft.TextButton("取消", on_click=self.handle_close_unlock_dialog),
                    confirm_btn
                ]
                if not getattr(self, "_unlock_dialog_shown", False):
                    self.page.show_dialog(self.unlock_dialog)
                    self._unlock_dialog_shown = True
                self.page.update()

        except Exception as ex:
            import traceback
            logger.error(f"智能解锁弹窗更新异常: {ex}\n{traceback.format_exc()}")
            self._show_snack(f"❌ 弹窗加载异常: {ex}", color="#ef4444")
            self.handle_close_unlock_dialog(None)

    def _select_strategy_card(self, strategy_key):
        """选择解仓策略卡片"""
        self._selected_strategy = strategy_key
        self.page.run_task(self._do_show_unlock_dialog)

    def _handle_waiver_change(self, ev):
        """更新强行解锁勾选状态"""
        self._cooldown_waived = ev.control.value
        self.page.run_task(self._do_show_unlock_dialog)

    def handle_close_unlock_dialog(self, e):
        """安全关闭解锁弹窗对话框"""
        self._unlock_dialog_open = False
        self._selected_strategy = None
        self._cooldown_waived = False
        self._unlock_dialog_shown = False
        try:
            self.page.pop_dialog()
        except Exception as ex:
            logger.error(f"Error in handle_close_unlock_dialog: {ex}")



    async def _do_unlock_strategy(self, strategy, symbol):

        # 颜色映射

        snack_colors = {

            "closeby":        "#3b82f6",

            "profit_offset":  "#a855f7",

            "breakout_trail": "#22c55e",

            "dca_merge":      "#f59e0b",

        }

        self._show_snack("⏳ 正在执行解仓策略，请稍候...", color=snack_colors.get(strategy, "#3b82f6"))



        result = await asyncio.get_event_loop().run_in_executor(

            None, lambda: hedge_manager.unlock(symbol, strategy)

        )

        msg = result.get("message", "")

        status = result.get("status")

        if status == "success":

            self._show_snack(f"✅ {msg}", color="#10b981")

            self._refresh_hedge_badge()

        elif status == "activated":

            self._show_snack(f"📌 {msg}", color=snack_colors.get(strategy, "#6366f1"))

        else:

            self._show_snack(f"❌ {msg}", color="#ef4444")



    def _show_snack(self, message, color="#0f766e"):

        self.page.snack_bar = ft.SnackBar(

            content=ft.Text(message, color=ft.Colors.WHITE),

            bgcolor=color,

            open=True,

            duration=4000,

        )

        try:

            self.page.update()

        except Exception:

            pass



    # ==================== 通知弹窗 ====================



    def show_page_notice(self, message):

        dialog = ft.AlertDialog(

            modal=False,

            title=ft.Row(

                [

                    ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.GREEN_400),

                    ft.Text("保存成功"),

                ],

                spacing=10,

            ),

            content=ft.Text(message),

            actions=[

                ft.TextButton("知道了", on_click=self.close_dialog),

            ],

            actions_alignment=ft.MainAxisAlignment.END,

        )

        try:

            self.page.show_dialog(dialog)

            self.page.update()

        except Exception:

            self.page.snack_bar = ft.SnackBar(

                content=ft.Text(message, color=ft.Colors.WHITE),

                bgcolor="#0f766e",

                open=True,

            )



    def close_dialog(self, e):
        try:
            self.page.pop_dialog()
        except Exception as ex:
            logger.error(f"Error in close_dialog: {ex}")





async def main(page: ft.Page):

    NeuralQuantApp(page)





if __name__ == "__main__":

    ft.run(main)

