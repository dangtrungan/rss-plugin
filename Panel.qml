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
// Nothing is fetched until the panel is opened or Refresh is pressed.
// Every string from the network is untrusted and rendered as plain text.
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

  property var feeds: []
  property var links: []
  property int selectedIndex: 0
  property bool loading: false
  property string status: ""
  property string updatedText: ""

  readonly property string headerStatus: {
    if (root.loading) return root.feeds.length === 0 ? "Loading…" : "Refreshing…"
    if (root.status !== "") return root.status
    return root.updatedText !== "" ? "Updated " + root.updatedText : ""
  }

  function open() {
    root.controller.show()
    root.refresh()
  }

  function refresh() {
    if (fetchProc.running) return
    root.loading = true
    root.status = ""
    fetchProc.running = true
  }

  function applyResults(raw) {
    var parsed = null
    try {
      parsed = JSON.parse(String(raw || "").trim())
    } catch (e) {
      parsed = null
    }
    root.loading = false
    if (!Array.isArray(parsed)) {
      root.status = "Unexpected output from fetch-feeds"
      return
    }

    var urls = []
    for (var i = 0; i < parsed.length; i++) {
      var items = parsed[i].items || []
      for (var j = 0; j < items.length; j++) {
        items[j].gi = urls.length
        urls.push(items[j].url)
      }
    }
    root.feeds = parsed
    root.links = urls
    root.selectedIndex = Math.min(root.selectedIndex, Math.max(0, urls.length - 1))
    root.status = ""
    root.updatedText = Qt.formatTime(new Date(), "HH:mm")
  }

  function moveSelection(delta) {
    if (root.links.length === 0) return
    root.selectedIndex = Math.max(0, Math.min(root.links.length - 1, root.selectedIndex + delta))
  }

  function openSelected() {
    if (root.selectedIndex < root.links.length) root.openUrl(root.links[root.selectedIndex])
  }

  // xdg-open gets the URL as its own argv element. Only http(s) is passed on.
  function openUrl(url) {
    if (!/^https?:\/\//.test(String(url))) return
    openProc.command = ["xdg-open", String(url)]
    openProc.running = true
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
    id: fetchProc
    command: ["python3", root.scriptPath]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyResults(text)
    }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.loading = false
        root.status = "Could not run fetch-feeds"
      }
    }
  }

  Process {
    id: openProc
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
      onMoveRequested: function(dx, dy) { root.moveSelection(dy) }
      onActivateRequested: root.openSelected()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "r" || t === "R") root.refresh()
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
              text: "NEWS"
              color: root.dimForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.bodySmall
              font.letterSpacing: 1
            }

            Text {
              anchors.left: heading.right
              anchors.leftMargin: Style.space(10)
              anchors.right: refreshButton.left
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

          Text {
            id: emptyNotice
            visible: root.feeds.length === 0 && !root.loading
            width: body.width
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: "No feeds loaded. Press refresh to try again."
            color: root.dimForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.body
          }

          Repeater {
            model: root.feeds

            Column {
              id: feedSection
              required property var modelData
              required property int index
              width: body.width
              spacing: Style.space(4)

              Text {
                width: feedSection.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: String(feedSection.modelData.name || "").toUpperCase()
                color: root.faintForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.caption
                font.letterSpacing: 1
                font.bold: true
              }

              Text {
                visible: !!feedSection.modelData.error
                width: feedSection.width
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                text: "Failed: " + String(feedSection.modelData.error)
                color: root.dimForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.bodySmall
              }

              Text {
                visible: !feedSection.modelData.error && (feedSection.modelData.items || []).length === 0
                width: feedSection.width
                textFormat: Text.PlainText
                text: "No items"
                color: root.dimForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.bodySmall
              }

              Repeater {
                model: feedSection.modelData.items || []

                Rectangle {
                  id: itemRow
                  required property var modelData

                  width: feedSection.width
                  height: rowText.implicitHeight + Style.space(12)
                  radius: Style.cornerRadius
                  readonly property bool selected: itemRow.modelData.gi === root.selectedIndex
                  color: itemRow.selected
                    ? Style.hoverFillFor(root.contentForeground, Commons.Color.accent)
                    : "transparent"

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
                      text: String(itemRow.modelData.title || "")
                      color: itemRow.selected
                        ? Style.hoverStateColor(root.contentForeground, Commons.Color.accent)
                        : root.contentForeground
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.body
                    }

                    Text {
                      visible: text !== ""
                      width: rowText.width
                      textFormat: Text.PlainText
                      text: root.relativeTime(itemRow.modelData.published)
                      color: root.meta
                      font.family: root.contentFontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }

                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: root.selectedIndex = itemRow.modelData.gi
                    onClicked: root.openUrl(itemRow.modelData.url)
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
