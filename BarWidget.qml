// Shell-provided singletons (Style.font) and the injected panel are untyped
// for qmllint, the same as in Omarchy's own plugins.
// qmllint disable missing-property
import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "dangtrungan.newsfeed"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function togglePanel() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  readonly property int unread: panelLoader.item ? panelLoader.item.unreadCount : 0

  implicitWidth: button.implicitWidth + badge.width
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  // The panel does no work until it is opened: no fetch, no timers.
  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarIconButton {
    id: button
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    width: implicitWidth
    bar: root.bar
    text: "\uf09e"
    slotSize: Style.bar.statusSlot
    tooltipText: root.unread > 0 ? "News Feed, " + root.unread + " unread" : "News Feed"

    onPressed: function(b) {
      if (b === Qt.LeftButton) root.togglePanel()
    }
  }

  Text {
    id: badge
    anchors.left: button.right
    anchors.verticalCenter: parent.verticalCenter
    width: visible ? implicitWidth + Style.space(4) : 0
    visible: !root.vertical && root.unread > 0
    text: root.unread > 99 ? "99+" : String(root.unread)
    color: root.bar ? root.bar.barForeground : Commons.Color.foreground
    font.family: root.bar ? root.bar.fontFamily : Style.font.family
    font.pixelSize: Style.font.caption
  }
}
