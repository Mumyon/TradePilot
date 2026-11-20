import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/network/api_client.dart';
import '../core/design/design_document.dart';
import '../features/trading/domain/trading_repository.dart';
import '../features/trading/domain/pending_order_store.dart';
import '../features/trading/presentation/trading_home_screen.dart';

import 'login_screen.dart';

class TradePilotApp extends StatefulWidget {
  const TradePilotApp({
    super.key,
    required this.repositoryFactory,
    this.api,
    this.pendingOrders,
    this.preferences,
  });
  final TradingRepository Function() repositoryFactory;
  final ApiClient? api;
  final PendingOrderStore? pendingOrders;
  final FlutterSecureStorage? preferences;
  @override
  State<TradePilotApp> createState() => _TradePilotAppState();
}

class _TradePilotAppState extends State<TradePilotApp> {
  static const _pilotKey = 'tradepilot.pilot_enabled';
  static const _invertKey = 'tradepilot.inverted_colors';
  static const _normalColors = ColorFilter.matrix([
    1,
    0,
    0,
    0,
    0,
    0,
    1,
    0,
    0,
    0,
    0,
    0,
    1,
    0,
    0,
    0,
    0,
    0,
    1,
    0,
  ]);
  static const _invertedColors = ColorFilter.matrix([
    -1,
    0,
    0,
    0,
    255,
    0,
    -1,
    0,
    0,
    255,
    0,
    0,
    -1,
    0,
    255,
    0,
    0,
    0,
    1,
    0,
  ]);
  bool _authenticated = false, _checking = true;
  bool _pilotEnabled = true, _invertColors = false;
  Future<void> _preferenceWrites = Future.value();
  @override
  void initState() {
    super.initState();
    widget.api?.onUnauthorized = () {
      if (mounted) setState(() => _authenticated = false);
    };
    _restore();
  }

  Future<void> _restore() async {
    final preferences = widget.preferences;
    if (preferences != null) {
      try {
        final values = await Future.wait([
          preferences.read(key: _pilotKey),
          preferences.read(key: _invertKey),
        ]);
        _pilotEnabled = values[0] != 'false';
        _invertColors = values[1] == 'true';
      } catch (_) {
        // The app can still open with its default display and Pilot settings.
      }
    }
    if (!mounted) return;
    bool authenticated = widget.api == null;
    try {
      authenticated = authenticated || await widget.api!.tokens.read() != null;
    } catch (_) {
      authenticated = false;
    }
    if (mounted) {
      setState(() {
        _authenticated = authenticated;
        _checking = false;
      });
    }
  }

  void _savePreference(String key, bool value) {
    final preferences = widget.preferences;
    if (preferences == null) return;
    _preferenceWrites = _preferenceWrites.then((_) async {
      try {
        await preferences.write(key: key, value: '$value');
      } catch (_) {
        debugPrint('TradePilot could not save the local preference $key.');
      }
    });
    unawaited(_preferenceWrites);
  }

  Future<void> _logout() async {
    try {
      await widget.api?.request('POST', '/v1/auth/logout');
    } catch (_) {}
    await widget.api?.tokens.clear();
    if (mounted) setState(() => _authenticated = false);
  }

  @override
  void dispose() {
    widget.api?.onUnauthorized = null;
    widget.api?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'TradePilot',
    debugShowCheckedModeBanner: false,
    builder: (context, child) => AnnotatedRegion<SystemUiOverlayStyle>(
      value: _invertColors
          ? SystemUiOverlayStyle.dark
          : SystemUiOverlayStyle.light,
      child: ColorFiltered(
        colorFilter: _invertColors ? _invertedColors : _normalColors,
        child: child,
      ),
    ),
    theme: ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      fontFamily: designFont,
      scaffoldBackgroundColor: const Color(0xFF0A0A0B),
      appBarTheme: AppBarTheme(
        systemOverlayStyle: _invertColors
            ? SystemUiOverlayStyle.dark
            : SystemUiOverlayStyle.light,
      ),
      colorScheme: ColorScheme.fromSeed(
        seedColor: Colors.white,
        brightness: Brightness.dark,
        primary: const Color(0xFFF5F5F2),
        onPrimary: const Color(0xFF0A0A0B),
        surface: const Color(0xFF151516),
        onSurface: const Color(0xFFF5F5F2),
      ),
      inputDecorationTheme: const InputDecorationTheme(
        filled: true,
        fillColor: Color(0xFF151516),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: Color(0xFF303034)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: Color(0xFF303034)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.zero,
          borderSide: BorderSide(color: Color(0xFFF5F5F2)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(shape: const RoundedRectangleBorder()),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(shape: const RoundedRectangleBorder()),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(shape: const RoundedRectangleBorder()),
      ),
      segmentedButtonTheme: const SegmentedButtonThemeData(
        style: ButtonStyle(
          shape: WidgetStatePropertyAll(RoundedRectangleBorder()),
        ),
      ),
      popupMenuTheme: const PopupMenuThemeData(
        shape: RoundedRectangleBorder(),
        color: Color(0xFF151516),
        surfaceTintColor: Colors.transparent,
      ),
      cardTheme: const CardThemeData(
        shape: RoundedRectangleBorder(),
        color: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: const RoundedRectangleBorder(),
          minimumSize: const Size(0, 48),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          shape: const RoundedRectangleBorder(),
          minimumSize: const Size(0, 48),
          side: const BorderSide(color: Color(0xFF303034)),
        ),
      ),
      dialogTheme: const DialogThemeData(
        shape: RoundedRectangleBorder(),
        backgroundColor: Color(0xFF151516),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        shape: RoundedRectangleBorder(),
        backgroundColor: Color(0xFF151516),
      ),
    ),
    home: _checking
        ? const Scaffold(body: Center(child: CircularProgressIndicator()))
        : _authenticated
        ? TradingHomeScreen(
            repositoryFactory: widget.repositoryFactory,
            pendingOrders: widget.pendingOrders,
            onLogout: widget.api == null ? null : _logout,
            pilotEnabled: _pilotEnabled,
            onPilotChanged: (value) {
              setState(() => _pilotEnabled = value);
              _savePreference(_pilotKey, value);
            },
            invertedColors: _invertColors,
            onInvertedColorsChanged: (value) {
              setState(() => _invertColors = value);
              _savePreference(_invertKey, value);
            },
          )
        : LoginScreen(
            api: widget.api!,
            onSuccess: () => setState(() => _authenticated = true),
          ),
  );
}
