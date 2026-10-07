import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../../features/trading/domain/trading_repository.dart';
import 'api_client.dart';

/// One foreground connection. The server issues short-lived, single-use tickets.
class MarketSocket {
  MarketSocket(this.api, {WebSocketChannel Function(Uri)? connect})
    : _connect = connect ?? WebSocketChannel.connect;
  final ApiClient api;
  final WebSocketChannel Function(Uri) _connect;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  final _states = StreamController<ConnectionState>.broadcast();
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _retry, _heartbeat;
  bool _running = false, _disposed = false;
  int _generation = 0, _attempt = 0;
  DateTime _lastMessage = DateTime.now();
  Stream<Map<String, dynamic>> get events => _events.stream;
  Stream<ConnectionState> get states => _states.stream;

  Future<void> start() async {
    if (_running || _disposed) return;
    _running = true;
    await _open(++_generation);
  }

  Future<void> _open(int generation) async {
    if (!_active(generation)) return;
    _states.add(
      _attempt == 0 ? ConnectionState.connecting : ConnectionState.reconnecting,
    );
    try {
      final ticket = await api.request('POST', '/v1/ws-ticket');
      if (!_active(generation)) return;
      final uri = api.baseUrl.replace(
        scheme: 'wss',
        path: '/v1/ws',
        queryParameters: {'ticket': ticket['ticket'] as String},
      );
      final channel = _connect(uri);
      _channel = channel;
      await channel.ready.timeout(const Duration(seconds: 10));
      if (!_active(generation)) {
        await channel.sink.close();
        return;
      }
      _lastMessage = DateTime.now();
      _subscription = channel.stream.listen(
        (raw) {
          if (!_active(generation)) return;
          try {
            final event = jsonDecode(raw as String) as Map<String, dynamic>;
            _lastMessage = DateTime.now();
            _attempt = 0;
            if (event['type'] == 'pong') return;
            _events.add(event);
          } catch (_) {
            // Bad frames must not crash the UI. Freshness still gates orders.
          }
        },
        onError: (Object _) => _lost(generation),
        onDone: () => _lost(generation),
        cancelOnError: true,
      );
      channel.sink.add(jsonEncode({'type': 'subscribe', 'channel': 'quotes'}));
      _states.add(ConnectionState.connected);
      _heartbeat = Timer.periodic(const Duration(seconds: 20), (_) {
        if (DateTime.now().difference(_lastMessage) >
            const Duration(seconds: 45)) {
          _lost(generation);
        } else {
          channel.sink.add(jsonEncode({'type': 'ping'}));
        }
      });
      // Reset backoff only after a received frame, not a short-lived handshake.
    } on ApiException catch (error) {
      if (!_active(generation)) return;
      if (error.statusCode == 401) {
        _running = false;
        _states.add(ConnectionState.disconnected);
      } else {
        _lost(generation);
      }
    } catch (_) {
      _lost(generation);
    }
  }

  bool _active(int generation) =>
      _running && !_disposed && generation == _generation;

  void _lost(int generation) {
    if (!_active(generation)) return;
    final next = ++_generation;
    _heartbeat?.cancel();
    unawaited(_subscription?.cancel());
    unawaited(_channel?.sink.close());
    _channel = null;
    _states.add(ConnectionState.reconnecting);
    final seconds = min(30, pow(2, min(_attempt++, 5)).toInt());
    _retry = Timer(
      Duration(milliseconds: seconds * 1000 + Random().nextInt(500)),
      () => unawaited(_open(next)),
    );
  }

  Future<void> pause() async {
    _running = false;
    ++_generation;
    _retry?.cancel();
    _heartbeat?.cancel();
    await _subscription?.cancel();
    await _channel?.sink.close();
    _channel = null;
    if (!_disposed) _states.add(ConnectionState.paused);
  }

  Future<void> dispose() async {
    await pause();
    _disposed = true;
    await _events.close();
    await _states.close();
  }
}
