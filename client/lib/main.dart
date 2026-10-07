import 'package:flutter/material.dart';

import 'app/tradepilot_app.dart';
import 'core/auth/token_store.dart';
import 'core/auth/secure_pending_order_store.dart';
import 'core/config/app_config.dart';
import 'core/network/api_client.dart';
import 'features/trading/data/demo_trading_repository.dart';
import 'features/trading/data/remote_trading_repository.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final config = AppConfig.fromEnvironment();
  final api = config.demo
      ? null
      : ApiClient(config.apiUrl, const SecureTokenStore());
  runApp(
    TradePilotApp(
      api: api,
      pendingOrders: config.demo
          ? null
          : const SecurePendingOrderStore(SecureTokenStore()),
      repositoryFactory: () =>
          config.demo ? DemoTradingRepository() : RemoteTradingRepository(api!),
    ),
  );
}
