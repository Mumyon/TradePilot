String? koreanMarketTime(Object? value, {bool seconds = false}) {
  final date = value is DateTime ? value : DateTime.tryParse('$value');
  if (date == null) return null;
  final stamp = date.toUtc().add(const Duration(hours: 9)).toIso8601String();
  return '${stamp.substring(5, 10)} ${stamp.substring(11, seconds ? 19 : 16)}';
}

String marketQuoteLabel({
  required bool available,
  required bool fresh,
  Map? session,
  DateTime? now,
}) {
  final at = (now ?? DateTime.now()).toUtc();
  final checked = DateTime.tryParse('${session?['checked_at']}');
  final opens = DateTime.tryParse('${session?['opens_at']}');
  final closes = DateTime.tryParse('${session?['closes_at']}');
  final validSchedule =
      checked != null &&
      !at.isBefore(checked) &&
      at.difference(checked) <= const Duration(minutes: 5);
  if (validSchedule && opens != null && closes != null) {
    if (at.isBefore(opens)) return '개장 전';
    if (!at.isBefore(closes)) return '장마감';
    if (fresh) return '장중';
  }
  if (validSchedule && session?['state'] == 'closed' && opens == null) {
    return '휴장';
  }
  if (!available) return '시세 확인 중';
  return fresh ? '시세 수신' : '시세 지연';
}
