"""统一弹窗策略：点外关闭、ESC 可关、点外点击不穿透。

## Quasar 的开关语义

读 `nicegui/static/quasar.umd.js` 源码确认（不是推测）：

- `onBackdropClick`（QDialog）：`persistent !== true && noBackdropDismiss !== true` 才关闭，
  否则抖动。
- `onEscapeKey`（QDialog）：`persistent === true || noEscDismiss === true` 就抖动，
  否则关闭。

合并成矩阵：

============================  ==========  ==========
prop                          点外点击    ESC
============================  ==========  ==========
（都不设）                     关闭        关闭
``no-backdrop-dismiss``       不关(抖动)  **关闭**
``persistent``                不关(抖动)  **不关(抖动)**
``no-esc-dismiss``            关闭        不关(抖动)
============================  ==========  ==========

**因此禁止使用 ``persistent`` 和 ``no-esc-dismiss``**：两者都会关掉 ESC，而"ESC 不要禁"
是硬要求。需要"点外不关但 ESC 可关"时只能用 ``no-backdrop-dismiss``。
`scripts/check_project.py` 里有对应的源码级拦截，改回去会被挡下。

当前策略：所有弹窗一律"点外可关、ESC 可关"，所以调用点直接用 ``ui.dialog()`` 即可，
不需要包一层工厂。

## 为什么这里没有 dialog() 包装函数

曾经有过一个 `dialogs.dialog()` 工厂，但它只是 `return ui.dialog()`，没有行为差异，却
把调用点从 `step_ai.ui.dialog` 改成了 `dialogs` 里的 `nicegui.ui`——于是
`patch("taskweave.desktop.components.step_ai.ui", MagicMock())` 这类既有测试替身失效，
弹窗变成真实弹窗并永久等待。**不要再引入这层间接**：策略靠 prop 门禁约束，不靠包装。

## 为什么需要穿透守卫

Quasar 的弹窗 DOM 是：

    .q-dialog                   position:fixed 全屏，pointer-events:none
      ├─ .q-dialog__backdrop    position:fixed 全屏，onClick = 点外关闭
      └─ .q-dialog__inner       position:fixed 全屏，pointer-events:none（只有卡片可点）

`.q-dialog__inner` 是**全屏**容器且不接收指针事件，所以"卡片之外"整片的命中目标就是
backdrop。实测确认：弹窗打开时 `elementFromPoint()` 在任何卡片外坐标都返回
`.q-dialog__backdrop`。

进一步用 Playwright 实测：在按下与抬起之间把弹窗层从 DOM 移除（模拟执行详情每秒重建
补参弹窗），Chrome **不会**把 click 派发到下层按钮——它因为按下目标已断开而取消了这次
click（实测事件序列为 pointerdown→backdrop、mousedown→DIV、mouseup→按钮，无 click）。

也就是说"单次点击同时关闭弹窗又点到下层按钮"在浏览器里不成立。守卫因此不是针对某条
已知路径的修复，而是**把"弹窗打开时点击不得落到页面内容上"变成结构上不可能**的加固：
只要按下时弹窗还开着、抬起时点击却指向页面内容，就吞掉这次点击。

守卫不依赖计时器，只在捕获阶段监听 document；`.q-menu` / `.q-tooltip` /
`.q-notification` / `.q-loading` 与卡片内容都属于正常覆盖层交互，一律放行——否则会
误伤弹窗里的 ``ui.select`` 下拉（下拉是 teleport 到 body 的 ``.q-menu``，不在
``.q-dialog`` 里）。
"""

# 判定分层：backdrop 属于"点外手势"（需要警戒），其余覆盖层属于"正常交互"（放行）。
OVERLAY_SELECTOR = ".q-dialog__inner, .q-menu, .q-tooltip, .q-notification, .q-loading"

OUTSIDE_CLICK_GUARD = """<script>
(function () {
  if (window.__twDialogGuardInstalled) { return; }
  window.__twDialogGuardInstalled = true;

  var OVERLAY = '__OVERLAY__';

  function hit(node, selector) {
    return !!(node && node.closest && node.closest(selector));
  }

  var armed = false;

  document.addEventListener('pointerdown', function (event) {
    if (hit(event.target, '.q-dialog__backdrop')) {
      // 点外手势：这次点击若最终落到页面上，必须拦下来。
      armed = true;
      return;
    }
    if (hit(event.target, OVERLAY)) {
      armed = false;
      return;
    }
    // 弹窗开着却按在页面内容上（重绘时序异常）：同样要拦。
    // backdrop 只在弹窗显示时才渲染，一次查询即可判断"是否有弹窗开着"。
    armed = document.querySelector('.q-dialog__backdrop') !== null;
  }, true);

  document.addEventListener('click', function (event) {
    if (!armed) { return; }
    armed = false;
    // 正常路径：交给 Quasar 自己处理点外关闭。
    if (hit(event.target, '.q-dialog__backdrop')) { return; }
    if (hit(event.target, OVERLAY)) { return; }
    // 弹窗层在按下与点击之间被重建，这次点击已经指向下层页面：吞掉它。
    event.stopPropagation();
    event.preventDefault();
  }, true);
}());
</script>""".replace("__OVERLAY__", OVERLAY_SELECTOR)


def install_outside_click_guard():
    """把穿透守卫装进所有页面的 head；重复调用是安全的。

    必须在 ``ui.run()`` 之前调用：``ui.run()`` 才会把共享 head 渲染出去，而在此之前
    还没有客户端，脚本不会执行。
    """
    from nicegui import ui

    ui.add_head_html(OUTSIDE_CLICK_GUARD, shared=True)
