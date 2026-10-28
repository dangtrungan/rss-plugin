// Shell-provided singletons (Style.font) and the injected panel are untyped
// for qmllint, the same as in Omarchy's own plugins.
// qmllint disable missing-property
import QtQuick
import qs.Commons
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

  implicitWidth: button.implicitWidth
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
    anchors.fill: parent
    bar: root.bar
    text: "\uf09e"
    slotSize: Style.bar.statusSlot
    tooltipText: "News Feed"

    onPressed: function(b) {
      if (b === Qt.LeftButton) root.togglePanel()
    }
  }
}
