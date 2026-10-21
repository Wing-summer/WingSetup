/*
 * Copyright (c) 2026, wingsummer
 * SPDX-License-Identifier: BSD-3-Clause
 * See LICENSE in the project root for license information.
 */

#include <QApplication>
#include <QDebug>
#include <QFile>
#include <QLabel>
#include <QPluginLoader>
#include <QTimer>
#include <QTranslator>
#include <cstdio>

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  // Keep every lookup relative to the deployed binary, not the working
  // directory.
  const auto base = QCoreApplication::applicationDirPath();
#ifdef Q_OS_MACOS
  // Keep resources out of code-only bundle directories so signing can seal
  // them.
  const auto resources = base + "/../Resources";
  const auto pluginPath = base + "/../PlugIns/demo_plugin.wingplg";
#else
  const auto resources = base;
  const auto pluginPath = base + "/plugin/demo_plugin.wingplg";
#endif
  for (const auto &path :
       {"scripts/startup.luau", "theme/style.qss", "settings.json"}) {
    QFile file(resources + "/" + path);
    if (!file.open(QIODevice::ReadOnly) || file.readAll().isEmpty()) {
      qCritical() << "Missing deployed resource" << path;
      return 2;
    }
  }
  QTranslator translator;
  if (!translator.load(resources + "/lang/demo_zh_CN.qm")) {
    qCritical() << "Translation did not load";
    return 3;
  }
  app.installTranslator(&translator);
  // Loading this module also exercises its separately deployed shared
  // dependency.
  QPluginLoader loader(pluginPath);
  auto *plugin = loader.instance();
  int value = 0;
  if (!plugin ||
      !QMetaObject::invokeMethod(plugin, "value", Q_RETURN_ARG(int, value)) ||
      value != 42) {
    qCritical() << "Plugin or private dependency failed"
                << loader.errorString();
    return 4;
  }
  const auto text =
      QCoreApplication::translate("Demo", "Deployed resources loaded");
  if (text == QStringLiteral("Deployed resources loaded")) {
    qCritical() << "Translation not applied";
    return 5;
  }
  QLabel label(text);
  label.resize(420, 80);
  if (app.arguments().contains("--smoke")) {
    QTimer::singleShot(0, &app, [&app] {
      std::puts("WIDGETS_DEPLOY_OK: translation, resources, .wingplg, private "
                "library");
      std::fflush(stdout);
      app.quit();
    });
  } else {
    label.show();
  }
  return app.exec();
}
