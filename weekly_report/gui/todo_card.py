"""메인 화면 '오늘 할 일' 카드 (나만의 비서 5-2·5-3) — TodoStore(DB)가 기준.

체크 = 직접 완료(대면·전화로 처리한 일, 17:00 자동 판정이 덮어쓰지 않음), ✕ = 사유를 골라 제외(되돌리기),
오늘·내일 각 VISIBLE_ROWS줄 + 더 보기. 추출은 버튼(5-4에서 09:00 자동 실행 예정).
Flet 0.86: Row 자식이 3개 이상이면 마지막이 안 그려질 수 있어 2개씩 중첩(pair).
"""

import asyncio
import os
import subprocess
from datetime import date, datetime, time, timedelta

import flet as ft

C = ft.Colors
VISIBLE_ROWS = 3
REMOVE_REASONS = ("내 업무 아님", "영향 없음·참고용", "이미 처리됨", "중복")
WEEKDAYS = "월화수목금토일"
PRIO_STYLE = {"높음": (C.RED_50, C.RED_700), "보통": (C.BLUE_50, C.BLUE_700), "일정": (C.GREEN_50, C.GREEN_700)}
KIND_ICON = {"요청": ft.Icons.MARK_EMAIL_UNREAD_OUTLINED, "내 약속": ft.Icons.HANDSHAKE_OUTLINED,
             "이월": ft.Icons.REDO, "일정": ft.Icons.EVENT, "새 요청": ft.Icons.FIBER_NEW_OUTLINED}


PRIO_RANK = {"높음": 0, "일정": 2, "보통": 3}
AUTO_CHECK_MINUTES = 30   # 자동 실행 확인 주기 — 실패하면 다음 확인 때 다시 시도
CHECK_TIME = time(17, 0)


def todo_due_action(now, holidays=(), has_am=False, has_pm=False, auto=True):
    """지금 자동으로 할 일 — 'am'(오늘 할 일 추출) / 'pm'(진행 점검) / None.
    근무일에 09:00이 지났는데 아침 추출을 안 했으면 am, 17:00이 지났고 아침 추출은 했는데 점검을 안 했으면 pm.
    그 시각에 PC가 꺼져 있었어도 프로그램을 켜는 순간 같은 판단으로 놓친 작업을 한다."""
    from weekly_report.ai.todos import WORK_START, is_workday
    if not auto or not is_workday(now.date(), holidays):
        return None
    if now.time() >= WORK_START and not has_am:
        return "am"
    if now.time() >= CHECK_TIME and has_am and not has_pm:
        return "pm"
    return None


def seconds_until_next_check(now):
    """다음 확인까지 초 — 30분마다 확인하되 09:00·17:00이 그 사이에 있으면 정각에 깨어남"""
    from weekly_report.ai.todos import WORK_START
    wait = timedelta(minutes=AUTO_CHECK_MINUTES)
    for t in (WORK_START, CHECK_TIME):
        at = datetime.combine(now.date(), t)
        if now < at < now + wait:
            wait = at - now
    return max(1, int(wait.total_seconds()) + 1)


def todo_sort_key(item):
    """화면 순서: 완료는 아래로, 높음 → 이월(오래된 것부터) → 일정(시간순) → 나머지"""
    return (item["status"] == "done", PRIO_RANK.get(item.get("priority"), 3) if not item.get("carry_count") else 1,
            -(item.get("carry_count") or 0), item.get("due") if item.get("kind") == "일정" else "", item["id"])


def pill(text, bg, fg):
    return ft.Container(ft.Text(text, size=11, color=fg, weight=ft.FontWeight.W_600),
                        bgcolor=bg, border_radius=10, padding=ft.Padding(8, 2, 8, 2))


def pair(a, b, spacing=8):
    return ft.Row([a, b], spacing=spacing, vertical_alignment=ft.CrossAxisAlignment.CENTER, tight=True)


def nest(items, spacing=6):
    while len(items) > 1:
        items = [pair(items[i], items[i + 1], spacing) if i + 1 < len(items) else items[i]
                 for i in range(0, len(items), 2)]
    return items[0] if items else ft.Container()


class TodoCardMixin:
    def create_todo_card(self):
        from weekly_report.storage.todos import TodoStore

        if not hasattr(self, "todo_store"):
            self.todo_store = TodoStore()
        self.todo_expanded = set()
        self.todo_busy = False
        self.todo_body = ft.Column(spacing=6)
        self.render_todo_card()
        return ft.Container(
            ft.Row([ft.Container(self.todo_body, bgcolor=C.WHITE, border=ft.Border.all(1, C.GREY_300),
                                 border_radius=12, padding=16, expand=True)]),
            padding=ft.Padding(24, 4, 24, 8))

    # ---------- 동작 ----------

    def _todo_today(self):
        return getattr(self, "todo_date", None) or date.today()

    def todo_check(self, item, value):
        self.todo_store.set_done(item["id"], value, by="manual")
        self.render_todo_card()

    def todo_remove(self, item, reason):
        self.todo_store.remove(item["id"], reason)
        self.render_todo_card()
        snack = ft.SnackBar(ft.Text(f"'{item['task']}' 항목을 제외했어요 (사유: {reason})"), action="되돌리기",
                            on_action=lambda e: self.todo_restore(item), duration=6000)
        self.page.overlay.append(snack)
        snack.open = True
        self.page.update()

    def todo_restore(self, item):
        self.todo_store.restore(item["id"])
        self.render_todo_card()

    def todo_toggle_more(self, bucket):
        self.todo_expanded ^= {bucket}
        self.render_todo_card()

    def todo_extract(self, e=None, force=False):
        """할 일 추출 (전 근무일 메일·Teams 분석, 수십 초) — Flet 0.86은 run_thread여야 화면이 갱신됨"""
        if self.todo_busy:
            return
        self.todo_busy = True
        self.render_todo_card(status="할 일 추출 중… (전 근무일 메일·Teams 분석)")

        def worker():
            try:
                from weekly_report.ai.todos import DailyTodos
                DailyTodos(store=self.todo_store).generate(self._todo_today(), force=force)
                message = "오늘 할 일을 정리했어요"
            except Exception as ex:
                print(f"Error extracting todos: {ex}")
                message = f"할 일 추출 실패: {ex}"
            self.todo_busy = False
            self.render_todo_card()
            self.show_snack(message)

        self.page.run_thread(worker)

    def todo_open_md(self, e=None):
        from weekly_report.ai.todos import TODO_DIR, export_markdown
        key = self._todo_today().isoformat()
        path = export_markdown(key, self.todo_store.list_for(key), out_dir=TODO_DIR)
        try:
            if os.name == "nt":
                os.startfile(path)  # noqa: S606 — 사용자가 누른 버튼으로 자기 파일 열기
            else:
                subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", path])
        except Exception as ex:
            self.show_snack(f"md 파일을 열 수 없습니다: {ex}")

    def todo_show_evidence(self, e=None):
        items = self.todo_store.list_for(self._todo_today().isoformat())
        rows = []
        for i in items:
            rows.append(ft.Text(i["task"], size=14, weight=ft.FontWeight.BOLD, color=C.BLACK))
            for ev in i.get("evidence") or []:
                rows.append(ft.Text(f"· {ev['text']}", size=12, color=C.GREY_700, selectable=True))
            if not i.get("evidence"):
                rows.append(ft.Text(f"· {i.get('source_label') or '근거 없음'}", size=12, color=C.GREY_600))
        dialog = ft.AlertDialog(title=ft.Text("할 일 근거"),
                                content=ft.Container(ft.Column(rows or [ft.Text("항목이 없어요")], scroll=ft.ScrollMode.AUTO,
                                                               spacing=4), width=760, height=480),
                                actions=[ft.TextButton("닫기", on_click=lambda e: self.page.pop_dialog())])
        self.page.show_dialog(dialog)

    # ---------- 그리기 ----------

    def _todo_row(self, item):
        done = item["status"] == "done"
        bg, fg = PRIO_STYLE.get(item.get("priority") or "보통", PRIO_STYLE["보통"])
        title = ft.Text(item["task"], size=14, weight=ft.FontWeight.W_600, color=C.GREY_500 if done else C.BLACK,
                        style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH) if done else None)
        if (item.get("carry_count") or 0) >= 2 and not done:
            title = pair(title, pill(f"🔴 {item['carry_count']}일째 이월", C.RED_50, C.RED_700), spacing=6)
        left = pair(
            ft.Checkbox(value=done, tooltip="직접 완료 체크 (대면·전화로 처리한 일)",
                        on_change=lambda e: self.todo_check(item, e.control.value)),
            ft.Column([pair(ft.Icon(KIND_ICON.get(item.get("kind"), ft.Icons.TASK_ALT), size=16, color=C.GREY_600),
                            title, spacing=6),
                       ft.Text(item.get("source_label") or "", size=12, color=C.GREY_600)], spacing=2),
            spacing=4)
        due = item.get("due") or ("기한 확인 필요" if item.get("kind") in ("요청", "내 약속") else "")
        badge = (pill("직접 완료" if item.get("done_by") == "manual" else "완료", C.GREEN_50, C.GREEN_700) if done
                 else pill(item.get("priority") or "보통", bg, fg))
        menu = self._todo_menu(item)
        due_color = C.ORANGE_800 if ("확인" in due or "지남" in due or due == "오늘") else C.GREY_700
        right = pair(pair(ft.Text(due, size=12, color=due_color, weight=ft.FontWeight.W_600), badge), menu, spacing=2)
        return ft.Container(ft.Row([left, right], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            padding=ft.Padding(4, 4, 4, 4), border=ft.Border(bottom=ft.BorderSide(1, C.GREY_200)))

    # ---------- 자동 실행 (5-4) ----------

    def start_todo_scheduler(self):
        """30분마다(09:00·17:00엔 정각에) todo_due_action 확인 — 켜자마자 한 번 확인하므로 놓친 09:00·17:00도 바로 실행.
        확인 자체는 DB 조회 2번이고, LLM은 실행할 때만 부른다."""
        async def loop():
            while True:
                try:
                    self._todo_auto_tick()
                except Exception as ex:
                    print(f"Warning: todo auto run check failed: {ex}")
                await asyncio.sleep(seconds_until_next_check(datetime.now()))
        self.page.run_task(loop)

    def _todo_auto_tick(self, now=None):
        from weekly_report.ai.rag import load_report_settings
        settings = load_report_settings()
        now = now or datetime.now()
        key = now.date().isoformat()
        if getattr(self, "todo_date", None) is None and self._todo_today() != now.date():
            self.render_todo_card()  # 자정을 넘기면 카드도 새 날짜로
        action = todo_due_action(now, settings.get("holidays", []), self.todo_store.has_run(key, "am"),
                                 self.todo_store.has_run(key, "pm"), settings.get("todo_auto", True))
        if not action or self.todo_busy:
            return None
        self.todo_mode = action
        if action == "am":
            self.todo_extract(force=False)
        else:
            self.todo_check_progress()
        return action

    # ---------- 17:00 진행 점검 ----------

    def todo_set_mode(self, mode):
        self.todo_mode = mode
        self.render_todo_card()

    def todo_check_progress(self, e=None):
        """17:00 진행 점검 (오늘 활동과 대조 + 새 요청) — 수십 초, run_thread"""
        if self.todo_busy:
            return
        self.todo_busy = True
        self.render_todo_card(status="진행 점검 중… (오늘 메일·Teams·문서 활동과 대조)")

        def worker():
            try:
                from weekly_report.ai.progress import ProgressCheck
                ProgressCheck(store=self.todo_store).run(self._todo_today())
                message = "오늘 진행 상황을 점검했어요"
            except Exception as ex:
                print(f"Error checking progress: {ex}")
                message = f"진행 점검 실패: {ex}"
            self.todo_busy = False
            self.render_todo_card()
            self.show_snack(message)

        self.page.run_thread(worker)

    def todo_confirm_carry(self, e=None):
        from weekly_report.ai.progress import ProgressCheck
        try:
            target, count = ProgressCheck(store=self.todo_store).confirm_carry(self._todo_today())
            self.show_snack(f"{target:%m/%d}({WEEKDAYS[target.weekday()]}) 목록으로 {count}건을 옮겼어요")
        except Exception as ex:
            self.show_snack(f"이월 실패: {ex}")
        self.render_todo_card()

    def _todo_pm_row(self, item):
        status = item["status"]
        label, (bg, fg, icon) = {
            "done": ("완료", (C.GREEN_50, C.GREEN_700, ft.Icons.CHECK_CIRCLE)),
            "in_progress": ("진행 중", (C.BLUE_50, C.BLUE_700, ft.Icons.PENDING)),
        }.get(status, ("미착수", (C.GREY_100, C.GREY_700, ft.Icons.RADIO_BUTTON_UNCHECKED)))
        how = {"manual": "직접 체크", "auto": "자동", "schedule": "일정"}.get(item.get("done_by") or "", "자동")
        note = ("사용자가 직접 완료 체크" if item.get("done_by") == "manual"
                else item.get("progress_note") or ("아직 점검 전" if status == "open" else ""))
        title = ft.Text(item["task"], size=14, weight=ft.FontWeight.W_600, color=C.BLACK)
        if (item.get("carry_count") or 0) >= 2 and status != "done":
            title = pair(title, pill(f"🔴 {item['carry_count']}일째 이월", C.RED_50, C.RED_700), spacing=6)
        left = pair(ft.Checkbox(value=status == "done", tooltip="직접 완료 체크 (대면·전화로 처리한 일)",
                                on_change=lambda e: self.todo_check(item, e.control.value)),
                    ft.Column([pair(ft.Icon(icon, color=fg, size=18), title, spacing=6),
                               ft.Text(f"근거: {note}", size=12, color=C.GREY_600)], spacing=2), spacing=4)
        right = pair(pair(ft.Text(how, size=11, color=C.GREY_500), pill(label, bg, fg)), self._todo_menu(item), spacing=2)
        return ft.Container(ft.Row([left, right], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            padding=ft.Padding(4, 4, 4, 4), border=ft.Border(bottom=ft.BorderSide(1, C.GREY_200)))

    def _todo_menu(self, item):
        return ft.PopupMenuButton(
            icon=ft.Icons.CLOSE, icon_size=18, tooltip="목록에서 제외",
            items=[ft.PopupMenuItem(content=ft.Text("제외 사유 선택", size=12, color=C.GREY_500))] + [
                ft.PopupMenuItem(content=ft.Text(r, size=13), on_click=lambda e, r=r: self.todo_remove(item, r))
                for r in REMOVE_REASONS])

    def _todo_list_section(self, key, title, items, row_fn):
        shown = items if key in self.todo_expanded else items[:VISIBLE_ROWS]
        controls = [ft.Text(f"{title} ({len(items)})", size=13, weight=ft.FontWeight.BOLD, color=C.GREY_800)]
        controls += [row_fn(i) for i in shown] or [ft.Text("없음", size=12, color=C.GREY_500)]
        if len(items) > VISIBLE_ROWS:
            expanded = key in self.todo_expanded
            controls.append(ft.TextButton("접기" if expanded else f"더 보기 ({len(items) - VISIBLE_ROWS}건)",
                                          icon=ft.Icons.EXPAND_LESS if expanded else ft.Icons.EXPAND_MORE,
                                          on_click=lambda e: self.todo_toggle_more(key)))
        return ft.Column(controls, spacing=2)

    # ---------- 그리기 ----------

    def _todo_tabs(self):
        def tab(label, mode):
            on = self.todo_mode == mode
            return ft.Container(ft.Text(label, size=13, weight=ft.FontWeight.BOLD if on else ft.FontWeight.NORMAL,
                                        color=C.WHITE if on else C.GREY_700),
                                bgcolor=C.BLUE_GREY_800 if on else C.GREY_100, border_radius=8,
                                padding=ft.Padding(12, 6, 12, 6), on_click=lambda e: self.todo_set_mode(mode))
        return pair(tab("09:00 오늘 할 일", "am"), tab("17:00 진행 점검", "pm"), spacing=6)

    def render_todo_card(self, status=None):
        today = self._todo_today()
        key = today.isoformat()
        if not hasattr(self, "todo_mode"):
            self.todo_mode = "pm" if (datetime.now().hour >= 17 or self.todo_store.has_run(key, "pm")) else "am"
        items = self.todo_store.list_for(key)
        today_items = sorted((i for i in items if i["bucket"] == "today"), key=todo_sort_key)
        tomorrow_items = sorted((i for i in items if i["bucket"] == "tomorrow"), key=todo_sort_key)
        if self.todo_mode == "am":
            manual = sum(i["status"] == "done" and i.get("done_by") == "manual" for i in items)
            carried = sum(i.get("kind") == "이월" for i in items)
            icon, name = ft.Icon(ft.Icons.WB_SUNNY_OUTLINED, color=C.ORANGE_600, size=22), "오늘 할 일"
            sub = (f"{today:%m월 %d일}({WEEKDAYS[today.weekday()]}) 목록 · 체크=직접 완료 · ✕=제외(사유 선택)" if items
                   else "아직 오늘 목록이 없어요 — '오늘 할 일 추출'을 누르면 전 근무일 메일·Teams를 분석해요")
            chips = nest([pill(f"오늘 {len(today_items)}", C.BLUE_50, C.BLUE_700),
                          pill(f"내일 {len(tomorrow_items)}", C.GREY_100, C.GREY_800),
                          pill(f"직접 완료 {manual}", C.GREEN_50, C.GREEN_700),
                          pill(f"이월 {carried}", C.PURPLE_50, C.PURPLE_700)])
            sections = ([self._todo_list_section("today", "오늘", today_items, self._todo_row),
                         self._todo_list_section("tomorrow", "내일", tomorrow_items, self._todo_row)] if items else [])
            primary = ft.Button("다시 추출" if items else "오늘 할 일 추출", icon=ft.Icons.AUTO_AWESOME,
                                disabled=self.todo_busy, on_click=lambda e: self.todo_extract(force=bool(items)),
                                tooltip="이미 체크·제외한 항목과 이월 항목은 그대로 두고 나머지만 다시 뽑아요" if items else None,
                                style=ft.ButtonStyle(bgcolor=C.BLUE, color=C.WHITE, shape=ft.RoundedRectangleBorder(radius=8)))
            secondary = ft.TextButton("근거 보기", icon=ft.Icons.FORMAT_LIST_NUMBERED, on_click=self.todo_show_evidence,
                                      disabled=not items)
            note = "근무일 09:00 자동 추출 · 17:00 자동 점검 (Settings > 나만의 비서)"
        else:
            done = sum(i["status"] == "done" for i in today_items)
            new_items = [i for i in tomorrow_items if i.get("kind") == "새 요청"]
            later = [i for i in tomorrow_items if i.get("kind") != "새 요청"]
            checked_at = self.todo_store.run_at(key, "pm")
            icon, name = ft.Icon(ft.Icons.NIGHTS_STAY_OUTLINED, color=C.INDIGO_400, size=22), "오늘 진행 점검"
            sub = (f"{today:%m월 %d일}({WEEKDAYS[today.weekday()]}) {checked_at[11:16]} 점검 · 판정이 틀리면 체크로 고치기"
                   if checked_at else "아직 점검 전이에요 — '진행 점검 실행'을 누르면 오늘 활동과 아침 목록을 대조해요")
            chips = nest([pill(f"완료 {done}", C.GREEN_50, C.GREEN_700),
                          pill(f"남은 일 {len(today_items) - done}", C.GREY_100, C.GREY_800),
                          pill(f"새 요청 {len(new_items)}", C.ORANGE_50, C.ORANGE_800)])
            bar = ft.Column([ft.Text(f"진행률 {done}/{len(today_items)} · 완료 안 된 항목은 다음 근무일 목록으로 이월",
                                     size=13, weight=ft.FontWeight.BOLD, color=C.GREY_800),
                             ft.ProgressBar(value=done / max(len(today_items), 1), color=C.GREEN_500,
                                            bgcolor=C.GREY_200, bar_height=8)], spacing=6)
            sections = [bar, self._todo_list_section("pm_today", "아침 할 일", today_items, self._todo_pm_row),
                        self._todo_list_section("pm_new", "오늘 새로 들어온 일 → 다음 근무일 목록", new_items + later,
                                                self._todo_row)]
            primary = ft.Button("내일로 이월 확정", icon=ft.Icons.REDO, disabled=self.todo_busy or not checked_at,
                                on_click=self.todo_confirm_carry,
                                tooltip="미완료·진행 중·새 요청을 다음 근무일 목록으로 옮겨요",
                                style=ft.ButtonStyle(bgcolor=C.INDIGO, color=C.WHITE, shape=ft.RoundedRectangleBorder(radius=8)))
            secondary = ft.TextButton("다시 점검" if checked_at else "진행 점검 실행", icon=ft.Icons.FACT_CHECK_OUTLINED,
                                      disabled=self.todo_busy or not items, on_click=self.todo_check_progress)
            note = "체크=직접 완료(자동 판정보다 우선) · ✕=제외"
        title = pair(pair(icon, ft.Text(name, size=18, weight=ft.FontWeight.BOLD, color=C.BLACK)), self._todo_tabs(),
                     spacing=16)
        header = ft.Row([ft.Column([title, ft.Text(status or sub, size=12,
                                                   color=C.ORANGE_800 if status else C.GREY_600)], spacing=4), chips],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        buttons = pair(pair(secondary, ft.TextButton("md 열기", icon=ft.Icons.DESCRIPTION_OUTLINED,
                                                     on_click=self.todo_open_md, disabled=not items)), primary)
        footer = ft.Row([ft.Text(note, size=12, color=C.GREY_500), buttons], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        self.todo_body.controls = [header, ft.Divider(height=8, color=C.GREY_200)] + sections + [footer]
        try:
            self.page.update()
        except Exception:
            pass
