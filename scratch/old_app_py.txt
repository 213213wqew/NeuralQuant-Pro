import asyncio
import base64
import io
import os
import sys
import time
import warnings
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
from quant_app.core.strategy_manager import strategy_runner
from quant_app.modules.ai.curve_analysis import CurveGateConfig, CurveSignalGate, curve_analysis_service
from quant_app.modules.data_collector.crawler_engine import data_engine, news_engine

logger = get_logger("AQuantUI")


class AQuantApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "A-Quant Professional Console"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0
        self.page.bgcolor = "#14181c"
        self.page.window_width = 1350
        self.page.window_height = 850

        self.current_symbol = "XAUUSD.c"
        self.env_path = mt5_client.env_path
        strategies_base_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "modules",
            "strategies",
        )
        self.strategy_preset_dirs = {
            "GridMartingaleMA01": os.path.join(strategies_base_dir, "grid_martingale_ma01", "presets"),
            "GridMartingaleMA02": os.path.join(strategies_base_dir, "grid_martingale_ma02", "presets"),
            "GridMartingaleMA03": os.path.join(strategies_base_dir, "grid_martingale_ma03", "presets"),
            "GridMartingaleMA04": os.path.join(strategies_base_dir, "grid_martingale_ma04", "presets"),
            "CompoundMartin": os.path.join(strategies_base_dir, "compound_martin", "presets"),
        }
        self.app_env = self.load_env_settings()
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
        self.active_main_tab = "home"
        self.secondary_refresh_running = False

        self.setup_ui()
        self.register_lifecycle_hooks()
        history_sync_service.start()

        if hasattr(flet_handler, "callback"):
            flet_handler.callback = self.on_backend_log

        self.page.run_task(self.update_loop)
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
            if strategy_runner.is_running:
                await asyncio.to_thread(strategy_runner.stop_and_clear, symbol=self.current_symbol)
            else:
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
                            ft.Text("A-Quant Pro", size=22, weight=ft.FontWeight.W_900),
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
                    ft.Row(
                        [
                            ft.Column([ft.Text("余额 (USD)", size=10, color=ft.Colors.GREY_500), self.balance_text], spacing=2),
                            ft.Column([ft.Text("浮动盈亏", size=10, color=ft.Colors.GREY_500), self.profit_text], spacing=2),
                            ft.Column(
                                [self.account_id_text, self.server_text],
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                                spacing=2,
                            ),
                        ],
                        spacing=30,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding(20, 10, 20, 10),
            bgcolor="#1c2127",
        )

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

        self.asset_bar = ft.Row(
            [
                self.asset_balance,
                self.asset_equity,
                self.asset_margin,
                ft.VerticalDivider(width=20),
                self.asset_profit,
            ],
            spacing=20,
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
        self.bottom_tab_view = ft.TabBarView(
            controls=[
                self.trade_list,
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

        control_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text("量化控制中心", size=16, weight=ft.FontWeight.BOLD),
                    ft.Divider(color="#2a2e39", height=1),
                    self.algo_switch,
                    
                    # 核心量化看板 (合并版)
                    ft.Container(
                        content=ft.Column([
                            # 第一行：策略与预设
                            ft.Row([
                                ft.Column([ft.Text("当前策略", size=9, color=ft.Colors.GREY_500), self.current_strategy_text], spacing=2, expand=1),
                                ft.Column([ft.Text("预设文件", size=9, color=ft.Colors.GREY_500), self.current_preset_text], spacing=2, expand=1, horizontal_alignment="end"),
                            ]),
                            ft.Divider(color="#23272e", height=1),
                            # 第二行：系统状态与健康度
                            ft.Row([
                                ft.Column([ft.Text("运行时间", size=9, color=ft.Colors.GREY_500), self.runtime_text], spacing=2, expand=1),
                                ft.Column([ft.Text("健康度", size=9, color=ft.Colors.GREY_500), self.margin_level_text], spacing=2, expand=1, horizontal_alignment="end"),
                            ]),
                            ft.Divider(color="#23272e", height=1),
                            # 第三行：AI 核心研判
                            ft.Row([
                                ft.Column([
                                    ft.Text("AI 风险评估", size=9, color=ft.Colors.GREY_500), 
                                    self.ai_risk_text,
                                    self.ai_phase_text
                                ], spacing=2, expand=1),
                                ft.Column([
                                    ft.Text("AI 动能信心", size=9, color=ft.Colors.GREY_500), 
                                    ft.Row([self.ai_dir_text, self.ai_dir_icon], spacing=5, alignment=ft.MainAxisAlignment.END, tight=True)
                                ], spacing=2, expand=1, horizontal_alignment="end"),
                            ]),
                        ], spacing=8),
                        padding=12,
                        bgcolor="#1c2127",
                        border_radius=8,
                        border=ft.border.all(1, "#2a2e39"),
                    ),

                    # 日志显示已移除以提升性能
                ],
                spacing=12,
            ),
            width=280,
            padding=15,
            bgcolor="#14181c",
        )

        return ft.Row(
            [
                ft.Column(
                    [
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
                                            self.chart_range_text,
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
                        self.chart_container,
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Container(
                                        self.asset_bar,
                                        padding=ft.padding.only(left=10, right=10, top=5),
                                    ),
                                    self.bottom_tabs,
                                ],
                                spacing=0,
                            ),
                            height=280,
                            bgcolor="#1c2127",
                            border=ft.border.only(top=ft.border.BorderSide(1, "#2a2e39")),
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

    def build_settings_view(self):
        self.mt5_path_input = ft.TextField(
            label="MT5 路径",
            value=self.app_env.get("MT5_PATH", mt5_client.mt5_path),
            expand=True,
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
        preset_options = [ft.dropdown.Option(name, name) for name in self.get_strategy_preset_names(strategy_value)]
        self.strategy_selector = ft.Dropdown(
            label="交易策略",
            options=[
                ft.dropdown.Option("GridMartingaleMA01", "GridMartingaleMA01"),
                ft.dropdown.Option("GridMartingaleMA02", "GridMartingaleMA02 (顺势单仓)"),
                ft.dropdown.Option("GridMartingaleMA03", "GridMartingaleMA03"),
                ft.dropdown.Option("GridMartingaleMA04", "GridMartingaleMA04"),
                ft.dropdown.Option("CompoundMartin", "利滚利(AI)"),
            ],
            value=strategy_value,
            border_color="#3a3f4b",
            on_select=self.on_strategy_changed,
        )
        preset_value = self.app_env.get("ACTIVE_PRESET")
        if preset_value not in [option.key for option in preset_options]:
            preset_value = preset_options[0].key if preset_options else None
        self.preset_selector = ft.Dropdown(
            label="策略预设 (.set)",
            options=preset_options,
            value=preset_value,
            border_color="#3a3f4b",
            visible=bool(preset_options),
        )
        self.current_preset_hint = ft.Text(
            f"当前预设: {strategy_runner.current_config_file or preset_value or '未选择'}",
            size=12,
            color=ft.Colors.GREY_500,
        )
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
        strategy_preset_row = ft.Row(
            [
                ft.Container(content=self.strategy_selector, width=240),
                ft.Container(content=self.preset_selector, width=300),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("当前使用的预设", size=11, color=ft.Colors.GREY_500),
                            self.current_preset_hint,
                        ],
                        spacing=6,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    expand=True,
                    padding=ft.padding.only(top=6),
                ),
            ],
            spacing=18,
            vertical_alignment=ft.CrossAxisAlignment.START,
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
                        facecolor="#14181c",
                        figcolor="#14181c",
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

        # --- 更新 AI 评分显示 ---
        risk_score = getattr(strategy_runner.current_strategy, 'latest_risk_score', 50.0)
        dir_score = getattr(strategy_runner.current_strategy, 'latest_dir_score', 50.0)
        
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

        # 移除碎片的单独 update()，由 update_loop 统一刷新
        self.asset_balance.value = f"结余: {acc['balance']:,.2f} USD"
        self.asset_equity.value = f"净值: {acc['equity']:,.2f}"
        self.asset_margin.value = f"可用预付款: {acc['margin_free']:,.2f}"
        self.asset_profit.value = f"{acc['profit']:+,.2f}"
        self.asset_profit.color = self._profit_color(acc["profit"])

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
        self.save_env_settings()
        selected_preset = self.preset_selector.value if self.preset_selector.visible else None
        self.current_preset_hint.value = f"当前预设: {selected_preset or '未选择'}"
        self.current_strategy_text.value = f"策略: {self.strategy_selector.value}"
        self.current_preset_text.value = f"预设: {selected_preset or '未选择'}"
        self.save_feedback_text.value = f"已保存：{self.strategy_selector.value} / {selected_preset or '无预设'}"
        self.save_feedback_box.visible = True
        self.show_page_notice(f"保存成功：{self.strategy_selector.value} / {selected_preset or '无预设'}")
        self.add_log(f"配置已保存，策略={self.strategy_selector.value}，预设={selected_preset or '无'}", "SUCCESS")
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
            self.runtime_text.value = "运行时间: 00:00:00"
        else:
            self.strategy_start_time = None
            self.add_log("正在关闭自动化并执行清场平仓...", "WARNING")
            res = await asyncio.to_thread(strategy_runner.stop_and_clear, symbol=self.current_symbol)
            count = res.get("count", 0)
            self.add_log(f"策略已停止，平仓数: {count}", "SUCCESS")
            self.runtime_text.value = "运行时间: -- (未启动自动执行)"
        self.runtime_text.visible = True
        self.page.update()

    async def on_strategy_changed(self, e):
        preset_names = self.get_strategy_preset_names(self.strategy_selector.value)
        self.preset_selector.options = [ft.dropdown.Option(name, name) for name in preset_names]
        self.preset_selector.visible = bool(preset_names)
        if self.preset_selector.visible and not self.preset_selector.value and self.preset_selector.options:
            self.preset_selector.value = self.preset_selector.options[0].key
        if self.preset_selector.value not in [option.key for option in self.preset_selector.options]:
            self.preset_selector.value = self.preset_selector.options[0].key if self.preset_selector.options else None
        selected_strategy = self.strategy_selector.value or "GridMartingaleMA01"
        selected_preset = self.preset_selector.value if self.preset_selector.visible else None
        if self.algo_switch.value:
            ok = await asyncio.to_thread(strategy_runner.set_strategy, selected_strategy, selected_preset)
            if ok:
                self.current_strategy_text.value = f"策略: {strategy_runner.strategy_name}"
                self.current_preset_text.value = f"预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"
                self.current_preset_hint.value = f"当前预设: {strategy_runner.current_config_file or selected_preset or '未选择'}"
                self.add_log(f"运行中策略已切换为: {strategy_runner.strategy_name}", "SUCCESS")
            else:
                self.add_log(f"策略切换失败: {selected_strategy}", "ERROR")
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
                    self.add_log(f"宸查€夋嫨 MT5 鏂囦欢: {selected}", "INFO")

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
        if data.get("ACTIVE_STRATEGY") not in {"GridMartingaleMA01", "GridMartingaleMA02", "GridMartingaleMA03", "GridMartingaleMA04", "CompoundMartin"}:
            data["ACTIVE_STRATEGY"] = "GridMartingaleMA01"
            data["ACTIVE_PRESET"] = None
        return data

    def save_env_settings(self):
        managed_keys = {"MT5_PATH", "ACTIVE_STRATEGY", "ACTIVE_PRESET"}
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
            self.page.dialog = dialog
            dialog.open = True
            self.page.update()
        except Exception:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(message, color=ft.Colors.WHITE),
                bgcolor="#0f766e",
                open=True,
            )

    def close_dialog(self, e):
        if getattr(self.page, "dialog", None):
            self.page.dialog.open = False
            self.page.update()


async def main(page: ft.Page):
    AQuantApp(page)


if __name__ == "__main__":
    ft.run(main)
