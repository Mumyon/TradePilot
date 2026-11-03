import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';

typedef DesignNode = Map<String, dynamic>;

/// The user's export is the source of truth, including the original SVG paths.
class DesignDocument {
  DesignDocument(this.colors, this.screens);
  final Map<String, dynamic> colors;
  final List<DesignNode> screens;

  static DesignDocument? _cached;
  static Future<DesignDocument> load() async => _cached ??= await _read();

  static Future<DesignDocument> _read() async {
    final json =
        jsonDecode(await rootBundle.loadString('assets/design/tradepilot.json'))
            as Map<String, dynamic>;
    return DesignDocument(json['colors'], (json['screens'] as List).cast());
  }

  DesignNode screen(int index) =>
      jsonDecode(jsonEncode(screens[index])) as DesignNode;

  Color color(String key) =>
      Color(int.parse('FF${(colors[key] as String).substring(1)}', radix: 16));
}

List<DesignNode> children(DesignNode node) =>
    (node['children'] as List? ?? []).cast<DesignNode>();
double number(DesignNode node, String key) => (node[key] as num).toDouble();

String get designFont => switch (defaultTargetPlatform) {
  TargetPlatform.iOS || TargetPlatform.macOS => 'Apple SD Gothic Neo',
  _ => 'Noto Sans KR',
};

/// Text, vectors and hit areas remain native widgets; no screen PNG is used.
/// Positions preserve the 390pt artboard. The host handles safe areas/scrolling.
class DesignCanvas extends StatelessWidget {
  const DesignCanvas({
    super.key,
    required this.document,
    required this.nodes,
    required this.size,
    required this.onAction,
    this.replacement,
    this.parentName = '',
    this.centerText = false,
  });
  final DesignDocument document;
  final List<DesignNode> nodes;
  final Size size;
  final ValueChanged<DesignNode> onAction;
  final Widget? Function(DesignNode node)? replacement;
  final String parentName;
  final bool centerText;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: size.width,
    height: size.height,
    child: Stack(
      clipBehavior: Clip.none,
      children: nodes.where((n) => n['hidden'] != true).map((node) {
        final x = number(node, 'x');
        final y = number(node, 'y');
        final width = number(node, 'w').clamp(0.0, size.width - x);
        final height = number(node, 'h');
        final name = node['name'] as String? ?? '';
        final custom = replacement?.call(node);
        Widget child;
        if (custom != null) {
          child = custom;
        } else if (node['type'] == 'text') {
          final fontSize = number(node, 'size');
          child = Baseline(
            baseline: fontSize * 1.12,
            baselineType: TextBaseline.alphabetic,
            child: SizedBox(
              width: width,
              child: Text(
                node['value'] as String,
                textAlign: centerText ? TextAlign.center : TextAlign.left,
                style: TextStyle(
                  fontFamily: designFont,
                  fontFamilyFallback: const ['Noto Sans KR'],
                  fontSize: fontSize,
                  height: (fontSize * 1.5).ceil() / fontSize,
                  fontWeight:
                      FontWeight.values[(node['weight'] as int) ~/ 100 - 1],
                  color: document.color(node['color']),
                  letterSpacing: 0,
                  decoration: TextDecoration.none,
                ),
              ),
            ),
          );
        } else if (node['type'] == 'rect') {
          child = ColoredBox(
            color: document
                .color(node['color'])
                .withValues(alpha: (node['opacity'] as num? ?? 1).toDouble()),
          );
        } else if (node['type'] == 'svg') {
          final w = number(node, 'w'), h = number(node, 'h');
          // Same viewport convention as the supplied Figma generator.
          child = SvgPicture.string(
            '<svg xmlns="http://www.w3.org/2000/svg" width="$w" height="$h" '
            'viewBox="0 0 ${w <= 24 ? 24 : w} ${w <= 24 && h <= 24 ? 24 : h}">'
            '${node['body']}</svg>',
            width: w,
            height: h,
          );
        } else if (node['type'] == 'group') {
          child = DesignCanvas(
            document: document,
            nodes: children(node),
            size: Size(width, height),
            onAction: onAction,
            replacement: replacement,
            parentName: name,
            centerText: node['centerText'] == true,
          );
        } else {
          child = const SizedBox.expand();
        }
        if (node['target'] != null || node['action'] != null) {
          child = Semantics(
            button: true,
            label: name,
            enabled: node['disabled'] != true,
            child: GestureDetector(
              key: ValueKey('action:$name'),
              behavior: HitTestBehavior.opaque,
              onTap: node['disabled'] == true ? null : () => onAction(node),
              child: child,
            ),
          );
        }
        return Positioned(
          left: x,
          top: y,
          width: width,
          // Figma's textAutoResize=HEIGHT allows wrapping beyond the source h.
          height: node['type'] == 'text' ? null : height,
          child: child,
        );
      }).toList(),
    ),
  );
}
