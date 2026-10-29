pragma ComponentBehavior: Bound
// Shell-provided singletons (Style.font) and the injected panel are untyped
// for qmllint, the same as in Omarchy's own plugins.
// qmllint disable missing-property
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Headlines from the feeds in ~/.config/omarchy-newsfeed/feeds.json.
// Only the local cache is read at startup; feeds are fetched when the panel
// is opened or Refresh is pressed. Every string from the network is untrusted
// and rendered as plain text.
Panel {
  id: root
  moduleName: "dangtrungan.newsfeed"
  ipcTarget: "dangtrungan.newsfeed"
  manageIpc: false

  property var anchorItem: null

  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color contentForeground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color dimForeground: Qt.darker(contentForeground, 1.5)
  readonly property color faintForeground: Qt.darker(contentForeground, 1.9)
  readonly property color meta: Qt.darker(contentForeground, 1.6)
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("bin/fetch-feeds").toString().replace(/^file:\/\//, ""))
  readonly property int limit: Math.max(1, Math.min(50, Math.floor(Number(root.setting("limit", 15))) || 15))

  property var feeds: []
  property var items: []
  property var seen: ({})
  property var pendingMarks: []
  property bool managing: false
  property string inputMode: ""
  property string filterText: ""
  property string pendingRemove: ""
  property string feedDoneText: ""
  property int selectedIndex: 0
  property bool loading: false
  property bool liveDone: false
  property string status: ""
  property string updatedText: ""

  readonly property var shown: {
    if (root.managing) return root.feeds
    var q = root.filterText.trim().toLowerCase()
    if (q === "") return root.items
    return root.items.filter(function(i) {
      return (String(i.title) + " " + String(i.source || "")).toLowerCase().indexOf(q) !== -1
    })
  }
  readonly property int unreadCount: root.items.filter(function(i) { return !root.isSeen(i.url) }).length

  readonly property string headerStatus: {
    if (root.loading) return root.feeds.length === 0 ? "Loading…" : "Refreshing…"
    if (root.status !== "") return root.status
    var parts = []
    if (root.unreadCount > 0) parts.push(root.unreadCount + " unread")
    if (root.updatedText !== "") parts.push("Updated " + root.updatedText)
    return parts.join(" · ")
  }

  Component.onCompleted: {
    cacheProc.running = true
    seenProc.running = true
  }

  function open() {
    root.controller.show()
    root.refresh()
  }

  function refresh() {
    if (fetchProc.running) return
    root.loading = true
    root.status = ""
    root.liveDone = false
    fetchProc.running = true
  }

  function parseList(raw) {
    try {
      var parsed = JSON.parse(String(raw || "").trim())
      return Array.isArray(parsed) ? parsed : null
    } catch (e) {
      return null
    }
  }

  function domainOf(url) {
    var m = /^https?:\/\/([^\/?#]+)/.exec(String(url))
    return m ? m[1].replace(/^www\./, "") : ""
  }

  function applyResults(raw, cached) {
    var parsed = root.parseList(raw)
    if (!cached) root.loading = false
    if (!parsed) {
      if (!cached) root.status = "Unexpected output from fetch-feeds"
      return
    }

    var all = []
    for (var i = 0; i < parsed.length; i++) {
      var items = parsed[i].items || []
      for (var j = 0; j < items.length; j++) {
        items[j].source = root.domainOf(items[j].url) || parsed[i].name
        all.push(items[j])
      }
    }
    all.sort(function(a, b) { return (Date.parse(b.published) || 0) - (Date.parse(a.published) || 0) })

    root.feeds = parsed
    root.items = all
    root.selectedIndex = Math.min(root.selectedIndex, Math.max(0, root.shown.length - 1))
    if (cached) return
    root.liveDone = true
    root.status = ""
    root.updatedText = Qt.formatTime(new Date(), "HH:mm")
  }

  function applySeen(raw) {
    var next = {}
    var list = root.parseList(raw) || []
    for (var i = 0; i < list.length; i++) {
      if (typeof list[i] === "string") next[list[i]] = true
    }
    root.seen = Object.assign(next, root.seen)
  }

  function isSeen(url) {
    return root.seen[String(url)] === true
  }

  function markRead(urls) {
    var next = Object.assign({}, root.seen)
    for (var i = 0; i < urls.length; i++) next[urls[i]] = true
    root.seen = next
    root.queueSeen("--mark-read", urls)
  }

  function unmarkRead(urls) {
    var next = Object.assign({}, root.seen)
    for (var i = 0; i < urls.length; i++) delete next[urls[i]]
    root.seen = next
    root.queueSeen("--unmark-read", urls)
  }

  // One read-state write at a time, in the order they were requested, so a
  // mark and an unmark of the same headline cannot swap places.
  function queueSeen(flag, urls) {
    root.pendingMarks = root.pendingMarks.concat([{ flag: flag, urls: urls }])
    root.flushMarks()
  }

  function flushMarks() {
    if (markProc.running || root.pendingMarks.length === 0) return
    var job = root.pendingMarks[0]
    root.pendingMarks = root.pendingMarks.slice(1)
    markProc.command = ["python3", root.scriptPath, job.flag].concat(job.urls)
    markProc.running = true
  }

  function markAll() {
    root.markRead(root.items.map(function(i) { return String(i.url) }))
    root.status = "Marked all read"
  }

  function unmarkItem() {
    var item = root.shown[root.selectedIndex]
    if (!root.managing && item) root.unmarkRead([String(item.url)])
  }

  function unmarkSource() {
    var item = root.shown[root.selectedIndex]
    if (root.managing || !item) return
    var urls = root.items.filter(function(i) { return i.source === item.source })
      .map(function(i) { return String(i.url) })
    root.unmarkRead(urls)
    root.status = "Unmarked " + urls.length + " from " + item.source
  }

  function moveSelection(delta) {
    if (root.shown.length === 0) return
    root.selectedIndex = Math.max(0, Math.min(root.shown.length - 1, root.selectedIndex + delta))
  }

  function openSelected() {
    var item = root.shown[root.selectedIndex]
    if (!root.managing && item) root.openItem(item)
  }

  function openItem(item) {
    root.markRead([String(item.url)])
    root.openUrl(item.url)
  }

  // Opens up to 10 unread headlines at once so one key press cannot flood the browser.
  function openUnread() {
    var urls = root.items.filter(function(i) { return !root.isSeen(i.url) })
      .map(function(i) { return String(i.url) })
      .slice(0, 10)
    if (urls.length === 0) {
      root.status = "No unread headlines"
      return
    }
    root.markRead(urls)
    Util.execArgv(["sh", "-c", 'for u in "$@"; do xdg-open "$u"; done', "sh"].concat(urls))
  }

  // xdg-open gets the URL as its own argv element. Only http(s) is passed on.
  function openUrl(url) {
    if (!/^https?:\/\//.test(String(url))) return
    Util.execArgv(["xdg-open", String(url)])
  }

  function focusInput() {
    Qt.callLater(function() { inputField.forceActiveFocus() })
  }

  function endInput() {
    root.inputMode = ""
    keyCatcher.forceActiveFocus()
  }

  function startFilter() {
    if (root.managing) return
    root.inputMode = "filter"
    inputField.text = root.filterText
    root.focusInput()
  }

  function startAdd() {
    if (!root.managing) return
    root.inputMode = "add"
    root.filterText = ""
    inputField.text = ""
    root.focusInput()
  }

  function toggleManage() {
    root.managing = !root.managing
    root.filterText = ""
    root.inputMode = ""
    inputField.text = ""
    root.pendingRemove = ""
    root.selectedIndex = 0
    keyCatcher.forceActiveFocus()
  }

  // Feed edits go through fetch-feeds, which writes only the entries it owns
  // and refuses to touch a feeds.json it cannot parse.
  function feedChange(args, doneText) {
    if (feedProc.running) return
    root.feedDoneText = doneText
    feedProc.command = ["python3", root.scriptPath].concat(args)
    feedProc.running = true
  }

  // First x arms the removal and the second x removes, so one stray key cannot delete a feed.
  function removeSelected() {
    var feed = root.managing ? root.feeds[root.selectedIndex] : null
    if (!feed || !feed.url) return
    if (root.pendingRemove !== feed.url) {
      root.pendingRemove = feed.url
      return
    }
    root.pendingRemove = ""
    root.feedChange(["--remove-feed", String(feed.url)], "Feed removed")
  }

  function relativeTime(iso) {
    if (!iso) return ""
    var t = Date.parse(iso)
    if (isNaN(t)) return ""
    var minutes = Math.floor((Date.now() - t) / 60000)
    if (minutes < 1) return "just now"
    if (minutes < 60) return minutes + "m ago"
    var hours = Math.floor(minutes / 60)
    if (hours < 24) return hours + "h ago"
    var days = Math.floor(hours / 24)
    if (days < 7) return days + "d ago"
    return Qt.formatDate(new Date(t), "d MMM yyyy")
  }

  Process {
    id: cacheProc
    command: ["python3", root.scriptPath, "--cached"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (!root.liveDone) root.applyResults(text, true)
    }
  }

  Process {
    id: seenProc
    command: ["python3", root.scriptPath, "--seen"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applySeen(text)
    }
  }

  Process {
    id: markProc
    onExited: root.flushMarks()
  }

  Process {
    id: fetchProc
    command: ["python3", root.scriptPath, "--limit", String(root.limit)]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyResults(text, false)
    }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.loading = false
        root.status = "Could not run fetch-feeds"
      }
    }
  }

  Process {
    id: feedProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var result = null
        try { result = JSON.parse(String(text).trim()) } catch (e) { result = null }
        if (result && result.ok) {
          root.refresh()
        } else {
          root.status = result && result.error ? String(result.error) : "Could not save feeds"
        }
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(body.implicitHeight, Style.space(520))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: inputField.activeFocus
      onMoveRequested: function(dx, dy) { root.moveSelection(dy) }
      onActivateRequested: root.openSelected()
      onCloseRequested: root.close()
      onDeleteRequested: root.removeSelected()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var key = t.toLowerCase()
        if (t === "U") root.unmarkSource()
        else if (key === "r") root.refresh()
        else if (key === "m") root.markAll()
        else if (key === "u") root.unmarkItem()
        else if (key === "o") root.openUnread()
        else if (key === "f") root.toggleManage()
        else if (key === "a") root.startAdd()
        else if (key === "/") root.startFilter()
      }

      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: body.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: body
          width: scroll.width
          spacing: Style.space(14)

          Item {
            id: header
            width: body.width
            height: refreshButton.height

            Text {
              id: heading
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.managing ? "FEEDS" : "NEWS"
              color: root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.bodySmall
              font.letterSpacing: 1
            }

            Text {
              anchors.left: heading.right
              anchors.leftMargin: Style.space(10)
              anchors.right: manageButton.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              elide: Text.ElideRight
              textFormat: Text.PlainText
              text: root.headerStatus
              color: root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.bodySmall
            }

            PanelActionButton {
              id: manageButton
              anchors.right: refreshButton.left
              anchors.rightMargin: Style.space(4)
              anchors.verticalCenter: parent.verticalCenter
              iconText: "\uf013"
              tooltipText: root.managing ? "Back to news (f)" : "Manage feeds (f)"
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              onClicked: root.toggleManage()
            }

            PanelActionButton {
              id: refreshButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              iconText: "\uDB81\uDC50"
              tooltipText: "Refresh (r)"
              foreground: root.contentForeground
              fontFamily: root.contentFontFamily
              enabled: !root.loading
              onClicked: root.refresh()
            }
          }

          TextField {
            id: inputField
            visible: root.inputMode !== "" || root.filterText !== ""
            width: body.width
            placeholderText: root.inputMode === "add"
              ? "Feed URL. Enter adds it, Esc cancels"
              : "Filter headlines. Enter keeps it, Esc clears it"
            foreground: root.contentForeground
            onTextEdited: if (root.inputMode === "filter") {
              root.filterText = text
              root.selectedIndex = 0
            }
            onAccepted: {
              if (root.inputMode === "add") {
                var url = text.trim()
                root.inputMode = ""
                if (url !== "") root.feedChange(["--add-feed", url], "Feed added")
                keyCatcher.forceActiveFocus()
              } else {
                root.endInput()
              }
            }
            Keys.onEscapePressed: {
              if (root.inputMode === "filter") root.filterText = ""
              text = ""
              root.endInput()
            }
          }

          Text {
            id: emptyNotice
            visible: root.shown.length === 0 && !root.loading
            width: body.width
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: root.managing
              ? "No feeds. Press a to add one."
              : root.feeds.length === 0
                ? "No feeds loaded. Press refresh to try again."
                : root.items.length === 0
                  ? "No headlines."
                  : "No headlines match the filter."
            color: root.dimForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.body
          }

          Repeater {
            model: root.feeds.filter(function(f) { return !!f.error })

            Text {
              required property var modelData
              width: body.width
              wrapMode: Text.WordWrap
              textFormat: Text.PlainText
              text: "Failed: " + String(modelData.name) + " (" + String(modelData.error) + ")"
              color: root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }

          Repeater {
            model: root.shown

            Rectangle {
              id: itemRow
              required property var modelData
              required property int index

              width: body.width
              height: rowText.implicitHeight + Style.space(12)
              radius: Style.cornerRadius
              readonly property bool selected: itemRow.index === root.selectedIndex
              readonly property bool isRead: !root.managing && root.isSeen(itemRow.modelData.url)
              color: itemRow.selected
                ? Style.hoverFillFor(root.contentForeground, Commons.Color.accent)
                : "transparent"

              onSelectedChanged: if (selected) {
                var top = mapToItem(scroll.contentItem, 0, 0).y
                if (itemRow.index === 0) scroll.contentY = 0
                else if (top < scroll.contentY) scroll.contentY = top
                else if (top + height > scroll.contentY + scroll.height)
                  scroll.contentY = top + height - scroll.height
              }

              Column {
                id: rowText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(2)

                Text {
                  width: rowText.width
                  wrapMode: Text.WordWrap
                  textFormat: Text.PlainText
                  text: root.managing ? String(itemRow.modelData.name || "") : String(itemRow.modelData.title || "")
                  color: itemRow.selected
                    ? Style.hoverStateColor(root.contentForeground, Commons.Color.accent)
                    : itemRow.isRead ? root.dimForeground : root.contentForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.body
                }

                Text {
                  visible: text.trim() !== ""
                  width: rowText.width
                  textFormat: Text.PlainText
                  text: root.managing
                    ? (String(itemRow.modelData.url) === root.pendingRemove
                        ? "Press x again to remove"
                        : String(itemRow.modelData.url || ""))
                    : root.relativeTime(itemRow.modelData.published) + "  " + String(itemRow.modelData.source || "")
                  color: root.meta
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onEntered: root.selectedIndex = itemRow.index
                onClicked: {
                  root.selectedIndex = itemRow.index
                  if (!root.managing) root.openItem(itemRow.modelData)
                }
              }
            }
          }
        }
      }
    }
  }
}
