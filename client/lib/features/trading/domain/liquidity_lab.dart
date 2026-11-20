import 'dart:math' as math;

/// Books use integer won or cents, so depth and budget comparisons share units.
int? moneyUnits(Object? value, String currency) {
  final match = RegExp(r'^(\d{1,10})(?:\.(\d+))?$').firstMatch('$value');
  if (match == null) return null;
  final scale = currency == 'USD' ? 100 : 1;
  final fraction = match[2] ?? '';
  final digits = currency == 'USD' ? 2 : 0;
  if (fraction.length > digits &&
      fraction.substring(digits).contains(RegExp('[1-9]'))) {
    return null;
  }
  final units = fraction.padRight(digits, '0').substring(0, digits);
  return int.parse(match[1]!) * scale + (int.tryParse(units) ?? 0);
}

typedef Level = ({int price, int shares});

class DepthBook {
  DepthBook(this.currency, this.at, this.asks, this.bids);

  factory DepthBook.parse(Map data) {
    final currency = data['currency'];
    final at = DateTime.tryParse('${data['as_of']}');
    if ((currency != 'KRW' && currency != 'USD') || at == null || !at.isUtc) {
      throw const FormatException('호가의 통화 또는 시각을 확인할 수 없습니다.');
    }
    List<Level> levels(String key, bool ascending) {
      final prices = <int, int>{};
      for (final row in (data[key] as List? ?? []).whereType<Map>()) {
        final price = moneyUnits(row['price'], currency);
        final shares = moneyUnits(row['volume'], 'KRW');
        if (price != null && price > 0 && shares != null && shares > 0) {
          // The feed exposes aggregated rows; do not double-count duplicates.
          prices[price] = math.max(prices[price] ?? 0, shares);
        }
      }
      return [
        for (final entry in prices.entries)
          (price: entry.key, shares: entry.value),
      ]..sort((a, b) => ascending
          ? a.price.compareTo(b.price)
          : b.price.compareTo(a.price));
    }

    return DepthBook(currency, at, levels('asks', true), levels('bids', false));
  }

  final String currency;
  final DateTime at;
  final List<Level> asks, bids;
  List<Level> levels(bool buy) => buy ? asks : bids;
  double? get mid {
    if (asks.isEmpty || bids.isEmpty || asks.first.price < bids.first.price) {
      return null;
    }
    return (asks.first.price + bids.first.price) / 2;
  }

  double? get spreadBps =>
      mid == null ? null : (asks.first.price - bids.first.price) / mid! * 10000;

  bool fresh(DateTime now) {
    final age = now.difference(at);
    return !age.isNegative && age <= const Duration(seconds: 30);
  }
}

class DepthFill {
  const DepthFill(this.filled, this.amount, this.worst);
  final int filled, amount;
  final int? worst;
  double? get average => filled == 0 ? null : amount / filled;
}

DepthFill walkDepth(
  DepthBook book, {
  required bool buy,
  int? quantity,
  int? budget,
  int? limit,
  int? maxBps,
}) {
  final levels = book.levels(buy);
  var filled = 0, amount = 0;
  int? worst;
  for (final level in levels) {
    if (limit != null && (buy ? level.price > limit : level.price < limit)) {
      break;
    }
    final first = levels.first.price;
    if (maxBps != null && (level.price - first).abs() * 10000 > first * maxBps) {
      break;
    }
    var take = math.min(level.shares, (quantity ?? 100000000) - filled);
    if (budget != null) take = math.min(take, (budget - amount) ~/ level.price);
    if (take <= 0) break;
    filled += take;
    amount += take * level.price;
    worst = level.price;
  }
  return DepthFill(filled, amount, worst);
}

double? depthBps(DepthBook book, bool buy, DepthFill fill) {
  final mid = book.mid;
  if (mid == null || fill.average == null) return null;
  return (buy ? fill.average! - mid : mid - fill.average!) / mid * 10000;
}

({DepthFill fill, DateTime? end}) splitDepth(
  List<DepthBook> frames, {
  required int slices,
  required int quantity,
  required bool buy,
  int? limit,
}) {
  DateTime? end;
  var filled = 0, amount = 0;
  int? worst;
  final count = math.min(slices, quantity);
  var step = 0;
  for (final frame in frames) {
    if (step >= count) break;
    if (end != null && !frame.at.isAfter(end)) continue;
    final target = quantity ~/ count + (step < quantity % count ? 1 : 0);
    final fill = walkDepth(frame, buy: buy, quantity: target, limit: limit);
    step++;
    end = frame.at;
    amount += fill.amount;
    filled += fill.filled;
    final level = fill.worst;
    if (level != null) {
      worst = worst == null ? level : (buy ? math.max(worst, level) : math.min(worst, level));
    }
  }
  return (fill: DepthFill(filled, amount, worst), end: end);
}

/// A print exactly at the limit can be on either side. These are scenarios
/// based on displayed volume and sampled prints, not queue position estimates.
({int optimistic, int conservative}) limitScenarios(
  DepthBook book,
  Iterable<Map> prints, {
  required bool buy,
  required int limit,
  required int quantity,
}) {
  final aggressive = walkDepth(book, buy: buy, quantity: quantity, limit: limit).filled;
  final ahead = book.levels(!buy).where((l) => l.price == limit)
      .fold<int>(0, (sum, l) => sum + l.shares);
  final dedup = <(DateTime, int, int)>{};
  var touch = 0, through = 0;
  for (final print in prints) {
    final when = DateTime.tryParse('${print['timestamp']}');
    final price = moneyUnits(print['price'], book.currency);
    final volume = moneyUnits(print['volume'], 'KRW');
    if (print['currency'] != book.currency ||
        when == null || !when.isAfter(book.at) || price == null ||
        price <= 0 || volume == null || volume <= 0 ||
        !dedup.add((when, price, volume))) {
      continue;
    }
    if (price == limit) touch += volume;
    if (buy ? price < limit : price > limit) through += volume;
  }
  return (
    optimistic: math.min(quantity, aggressive + touch + through),
    conservative: math.min(quantity, aggressive + math.max(0, through - ahead)),
  );
}
