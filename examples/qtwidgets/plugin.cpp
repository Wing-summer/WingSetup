/*
 * Copyright (c) 2026, wingsummer
 * SPDX-License-Identifier: BSD-3-Clause
 * See LICENSE in the project root for license information.
 */

#include <QObject>
extern "C" int private_value();
class DemoPlugin : public QObject {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.example.Widgets.Demo")
public:
    Q_INVOKABLE int value() const { return private_value(); }
};
#include "plugin.moc"
