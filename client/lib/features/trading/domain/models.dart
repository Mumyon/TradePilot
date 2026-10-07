class Quote {
  const Quote({
    required this.symbol,
    required this.name,
    required this.priceWon,
    required this.asOf,
    required this.sequence,
  });
  final String symbol;
  final String name;
  final int priceWon;
  final DateTime asOf;
  final int sequence;
  bool isFresh(DateTime now) {
    final age = now.difference(asOf);
    return age >= Duration.zero && age <= const Duration(seconds: 15);
  }

  factory Quote.fromJson(Map<String, dynamic> json) => Quote(
    symbol: json['symbol'] as String,
    name: json['name'] as String,
    priceWon: int.parse(json['price_won'] as String),
    asOf: DateTime.parse(json['as_of'] as String).toUtc(),
    sequence: json['sequence'] as int,
  );
}

class Prediction {
  const Prediction({
    required this.up,
    required this.neutral,
    required this.down,
    required this.generatedAt,
    required this.validUntil,
    required this.modelVersion,
  });
  final double up, neutral, down;
  final DateTime generatedAt, validUntil;
  final String modelVersion;
  String get direction {
    if (up >= .65) return '상승';
    if (neutral >= .65) return '중립';
    if (down >= .65) return '하락';
    return '방향 판단 보류';
  }

  factory Prediction.fromJson(Map<String, dynamic> json) {
    final probabilities = [
      'up',
      'neutral',
      'down',
    ].map((key) => (json[key] as num).toDouble()).toList();
    if (probabilities.any((p) => !p.isFinite || p < 0 || p > 1) ||
        (probabilities.reduce((a, b) => a + b) - 1).abs() > .001) {
      throw const FormatException('Invalid prediction probabilities');
    }
    return Prediction(
      up: probabilities[0],
      neutral: probabilities[1],
      down: probabilities[2],
      generatedAt: DateTime.parse(json['generated_at'] as String).toUtc(),
      validUntil: DateTime.parse(json['valid_until'] as String).toUtc(),
      modelVersion: json['model_version'] as String,
    );
  }
}

enum OrderSide { buy, sell }

class OrderDraft {
  const OrderDraft({
    required this.symbol,
    required this.side,
    required this.quantity,
    required this.limitPriceWon,
    required this.pilotEnabled,
  });
  final String symbol;
  final OrderSide side;
  final int quantity, limitPriceWon;
  final bool pilotEnabled;
  Map<String, dynamic> toJson() => {
    'symbol': symbol,
    'side': side.name,
    'quantity': quantity,
    'limit_price_won': '$limitPriceWon',
    'order_type': 'limit',
    'pilot_enabled': pilotEnabled,
  };
}

class OrderCheck {
  const OrderCheck({
    required this.id,
    required this.allowed,
    required this.messages,
    required this.expiresAt,
  });
  final String id;
  final bool allowed;
  final List<String> messages;
  final DateTime expiresAt;
  factory OrderCheck.fromJson(Map<String, dynamic> json) => OrderCheck(
    id: json['check_id'] as String,
    allowed: json['allowed'] as bool,
    messages: (json['messages'] as List).cast<String>(),
    expiresAt: DateTime.parse(json['expires_at'] as String).toUtc(),
  );
}

class OrderReceipt {
  const OrderReceipt({
    required this.id,
    required this.symbol,
    required this.status,
  });
  final String id, symbol, status;
  factory OrderReceipt.fromJson(Map<String, dynamic> json) => OrderReceipt(
    id: json['order_id'] as String,
    symbol: json['symbol'] as String,
    status: json['status'] as String,
  );
}
