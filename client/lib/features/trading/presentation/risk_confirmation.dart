import 'package:flutter/material.dart';
import '../domain/models.dart';

class RiskConfirmation extends StatefulWidget {
  const RiskConfirmation({
    super.key,
    required this.check,
    this.draft,
    this.onPresented,
  });
  final VoidCallback? onPresented;
  final OrderCheck check;
  final OrderDraft? draft;
  @override
  State<RiskConfirmation> createState() => _RiskConfirmationState();
}

class _RiskConfirmationState extends State<RiskConfirmation> {
  final _reason = TextEditingController();
  bool _ack = false, _high = false;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.onPresented?.call();
    });
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final check = widget.check;
    final panic = (check.behavior['items'] as List? ?? []).any(
      (item) => item['code'] == 'panic' && item['status'] == 'hit',
    );
    final contextData = check.analysis['context'] as Map? ?? {};
    final ready =
        (!check.requiresAck || _ack) &&
        (!check.requiresAck || _reason.text.trim().length >= 3) &&
        (!check.requiresHighAck || _high);
    return AlertDialog(
      title: Text(
        panic
            ? '잠깐, 계획된 매도인가요?'
            : check.requiresHighAck
            ? '행동 경고 · 높음'
            : check.requiresAck
            ? '행동 경고 · 주의'
            : '거래 이유 및 계획 확인',
      ),
      content: SizedBox(
        width: 360,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (widget.draft case final draft?)
                Text(
                  '${draft.symbol} · ${draft.side == OrderSide.buy ? '매수' : '매도'} ${draft.quantity}주\n지정가 ${draft.limitPriceWon}원 · 합계 ${draft.limitPriceWon * draft.quantity}원',
                ),
              const SizedBox(height: 12),
              Text(
                check.behavior['enabled'] == true
                    ? '행동 점수 ${check.behavior['score'] ?? 0}/100${check.behavior['partial'] == true ? ' · 일부 판단 불가' : ''}'
                    : '행동 점검 OFF · 위험 규칙은 적용',
              ),
              for (final item in check.behavior['items'] as List? ?? [])
                if (item['status'] == 'hit')
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      '${item['title']} +${item['points']} · ${item['message']}',
                    ),
                  ),
              if (panic) ...[
                const SizedBox(height: 8),
                Text(
                  '보유 평가수익률 ${contextData['position_return_percent'] ?? '확인 불가'}%',
                ),
                Text(
                  contextData['stop_loss_won'] == null
                      ? '등록된 손절 기준 없음'
                      : '저장된 손절가 ${contextData['stop_loss_won']}원',
                ),
                Text('${contextData['plan_message'] ?? '사전 계획을 확인하세요.'}'),
              ],
              if (check.requiresHighAck)
                const Text('높음 단계 · 계획과 주문 내용을 다시 확인하세요.'),
              const Text(
                '감정 진단이 아닌 행동 규칙에 따른 안내입니다.',
                style: TextStyle(fontSize: 12),
              ),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: const Text('전체 점검 근거 보기'),
                children: [Text(check.messages.join('\n\n'))],
              ),
              const SizedBox(height: 16),
              TextField(
                key: const ValueKey('trade-reason'),
                controller: _reason,
                maxLength: 1000,
                maxLines: 3,
                decoration: InputDecoration(
                  labelText: check.requiresAck
                      ? '이번 거래 이유 (3자 이상)'
                      : '이번 거래 이유 (선택)',
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (check.requiresAck)
                CheckboxListTile(
                  key: const ValueKey('warning-ack'),
                  contentPadding: EdgeInsets.zero,
                  title: const Text('경고 근거를 확인했습니다.'),
                  value: _ack,
                  onChanged: (v) => setState(() => _ack = v!),
                ),
              if (check.requiresHighAck)
                CheckboxListTile(
                  key: const ValueKey('high-risk-ack'),
                  contentPadding: EdgeInsets.zero,
                  title: const Text('계획과 주문 내용을 다시 확인했습니다.'),
                  value: _high,
                  onChanged: (v) => setState(() => _high = v!),
                ),
              const Text(
                '이유를 입력해도 경고 점수나 위험 규칙 위반은 해제되지 않습니다.',
                style: TextStyle(fontSize: 12),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, {
            'deferred': true,
            'reason': _reason.text.trim(),
          }),
          child: const Text('주문 보류'),
        ),
        FilledButton(
          onPressed: ready
              ? () => Navigator.pop(context, {
                  'reason': _reason.text.trim(),
                  'high': _high,
                })
              : null,
          child: const Text('확인 후 주문 진행'),
        ),
      ],
    );
  }
}
