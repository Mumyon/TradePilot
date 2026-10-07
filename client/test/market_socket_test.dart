import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:tradepilot_client/core/network/api_client.dart';
import 'package:tradepilot_client/core/network/market_socket.dart';
import 'package:tradepilot_client/features/trading/domain/trading_repository.dart';

import 'api_client_test.dart' show MemoryTokens;

void main() {
  test(
    'real local WebSocket subscribes, delivers event and reconnects with new ticket',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final peers = <WebSocket>[];
      final messages = <String>[];
      var tickets = 0;
      final listener = server.listen((request) async {
        expect(request.uri.queryParameters['ticket'], startsWith('ticket-'));
        final peer = await WebSocketTransformer.upgrade(request);
        peers.add(peer);
        peer.listen((raw) {
          final json = jsonDecode(raw as String) as Map<String, dynamic>;
          messages.add(json['type'] as String);
          if (json['type'] == 'subscribe') {
            peer.add(
              jsonEncode({
                'type': 'quote',
                'data': {'symbol': '005930'},
              }),
            );
          }
          if (json['type'] == 'ping') peer.add('{"type":"pong"}');
        });
      });
      final api = ApiClient(
        Uri.parse('https://127.0.0.1:${server.port}'),
        MemoryTokens(),
        client: MockClient((request) async {
          expect(request.url.path, '/v1/ws-ticket');
          return http.Response(
            jsonEncode({'ticket': 'ticket-${++tickets}'}),
            200,
          );
        }),
      );
      final socket = MarketSocket(
        api,
        connect: (uri) => WebSocketChannel.connect(uri.replace(scheme: 'ws')),
      );
      final events = <Map<String, dynamic>>[];
      final states = <ConnectionState>[];
      final eventSubscription = socket.events.listen(events.add);
      final stateSubscription = socket.states.listen(states.add);
      addTearDown(() async {
        await socket.dispose();
        await eventSubscription.cancel();
        await stateSubscription.cancel();
        for (final peer in peers) {
          await peer.close();
        }
        await listener.cancel();
        await server.close(force: true);
        api.close();
      });
      await socket.start();
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(events.single['type'], 'quote');
      expect(messages, contains('subscribe'));
      await peers.first.close();
      await Future<void>.delayed(const Duration(seconds: 2));
      expect(tickets, 2);
      expect(events.length, 2);
      expect(states, contains(ConnectionState.reconnecting));
      await socket.pause();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(states.last, ConnectionState.paused);
    },
  );
}
