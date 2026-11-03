import 'models.dart';

class PendingOrder {
  const PendingOrder(this.draft, this.check, this.key);
  final OrderDraft draft;
  final OrderCheck check;
  final String key;

  Map<String, dynamic> toJson() => {
    'draft': draft.toJson(),
    'key': key,
    'check': {
      'check_id': check.id,
      'allowed': check.allowed,
      'messages': check.messages,
      'expires_at': check.expiresAt.toIso8601String(),
      'analysis': check.analysis,
      ...check.confirmationJson,
    },
  };
  factory PendingOrder.fromJson(Map<String, dynamic> json) {
    final draft = json['draft'] as Map<String, dynamic>;
    return PendingOrder(
      OrderDraft(
        symbol: draft['symbol'] as String,
        side: OrderSide.values.byName(draft['side'] as String),
        quantity: draft['quantity'] as int,
        limitPriceWon: int.parse(draft['limit_price_won'] as String),
        pilotEnabled: draft['pilot_enabled'] as bool,
        planId: draft['plan_id'] as String?,
      ),
      OrderCheck.fromJson(json['check'] as Map<String, dynamic>),
      json['key'] as String,
    );
  }
}

abstract interface class PendingOrderStore {
  Future<PendingOrder?> load();
  Future<void> save(PendingOrder order);
  Future<void> clear();
}

class MemoryPendingOrderStore implements PendingOrderStore {
  PendingOrder? _order;
  @override
  Future<PendingOrder?> load() async => _order;
  @override
  Future<void> save(PendingOrder order) async {
    _order = order;
  }

  @override
  Future<void> clear() async {
    _order = null;
  }
}
