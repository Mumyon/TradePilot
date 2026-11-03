import 'dart:async';

import 'package:flutter/material.dart';

import '../domain/workspace_repository.dart';

/// Narrative review only after the server confirms both research runs have ended.
class AIReplayReview extends StatefulWidget {
  const AIReplayReview({
    super.key,
    required this.repository,
    required this.runId,
  });
  final WorkspaceRepository repository;
  final String runId;

  @override
  State<AIReplayReview> createState() => _AIReplayReviewState();
}

class _AIReplayReviewState extends State<AIReplayReview> {
  Map<String, dynamic> _review = {};
  String? _error;
  bool _busy = false;
  Timer? _timer;
  int _polls = 0;

  String get _path => '/v1/replay/runs/${widget.runId}/ai-review';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool create = false}) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.repository.workspaceRequest(
        create ? 'POST' : 'GET',
        _path,
        body: create ? {'consent': true} : null,
      );
      if (!mounted) return;
      setState(() => _review = result);
      _timer?.cancel();
      if (['pending', 'generating'].contains(result['status']) && _polls < 40) {
        _timer = Timer(const Duration(seconds: 2), () {
          _polls++;
          _load();
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'AI 복기 연결을 확인해 주세요. 기존 행동 피드백은 계속 볼 수 있습니다.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _generate() async {
    final consent = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ChatGPT로 AI 복기 생성'),
        content: const Text(
          '이 실험의 행동 집계를 OpenAI에 전달합니다. 종목명·날짜·계좌정보·입력한 이유는 보내지 않습니다. '
          '본인 ChatGPT 구독 한도를 사용하며 별도 유료 API로 전환하지 않습니다. '
          '생성한 해설은 연구 기록에 저장됩니다. 계속할까요?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('닫기'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('동의하고 생성'),
          ),
        ],
      ),
    );
    if (consent == true && mounted) {
      _polls = 0;
      await _load(create: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = _review['status'];
    final result = _review['result'] as Map?;
    final facts = {
      for (final f in _review['facts'] as List? ?? []) f['fact_id']: f['text'],
    };
    return Card(
      key: const ValueKey('ai-review-card'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'ChatGPT AI 복기',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              'ON/OFF 두 실험 종료 후 제공하는 선택 기능입니다. 서버 집계와 AI 해설을 구분해 확인하세요.',
            ),
            const SizedBox(height: 8),
            if (_error != null) Text(_error!),
            if (_review['message'] is String)
              Text(_review['message'] as String),
            if (_busy) const Text('연결 상태 확인 중…'),
            if (status == 'pending' || status == 'generating')
              const Text('AI 복기 생성 중입니다. 결과를 받으면 여기에 표시합니다.'),
            if (status == 'available' && result != null) ...[
              for (final item in result['observations'] as List) ...[
                const SizedBox(height: 12),
                Text(
                  '서버 집계 · ${facts[item['fact_id']] ?? ''}',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                Text('AI 해설 · ${item['interpretation']}'),
                Text('돌아볼 질문 · ${item['reflection_question']}'),
              ],
              const SizedBox(height: 12),
              Text('해석의 한계 · ${result['limitation']}'),
              const Text('생성형 AI의 해설은 사실 확인이 필요하며 감정 진단·주가 예측·주문 지시가 아닙니다.'),
              ExpansionTile(
                title: const Text('AI 복기 생성 기록'),
                children: [
                  Text(
                    '모델 ${_review['response_model'] ?? _review['requested_model']}',
                  ),
                  Text('설명 버전 ${_review['prompt_version']}'),
                  Text('완료 시각 ${_review['completed_at'] ?? ''}'),
                ],
              ),
            ],
            Wrap(
              children: [
                if (status == 'ready' || _review['can_retry'] == true)
                  OutlinedButton(
                    key: const ValueKey('ai-review-generate'),
                    onPressed: _busy ? null : _generate,
                    child: Text(status == 'ready' ? 'AI 복기 생성' : 'AI 복기 다시 요청'),
                  ),
                TextButton(
                  key: const ValueKey('ai-review-refresh'),
                  onPressed: _busy
                      ? null
                      : () {
                          _polls = 0;
                          _load();
                        },
                  child: const Text('AI 연결 상태 새로고침'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
