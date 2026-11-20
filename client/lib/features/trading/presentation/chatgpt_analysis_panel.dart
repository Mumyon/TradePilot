import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import '../../../core/network/api_client.dart';

import '../domain/workspace_repository.dart';
import 'market_quote_status.dart';
import 'trading_layout_bindings.dart' show won;

/// Quant analysis before an order, or narrative review after paired research runs.
class ChatGPTAnalysisPanel extends StatefulWidget {
  const ChatGPTAnalysisPanel({
    super.key,
    required this.repository,
    required this.runId,
    this.onStartTraining,
  }) : currentPrice = null,
       checkId = null,
       decisionPath = null,
       decisionTitle = null,
       autoGenerate = false,
       journalReview = false,
       journalConsentMessage = null,
       onStatusChanged = null;
  const ChatGPTAnalysisPanel.pretrade({
    super.key,
    required this.repository,
    required this.checkId,
    this.autoGenerate = false,
    this.currentPrice,
    this.onStatusChanged,
  }) : journalReview = false,
       journalConsentMessage = null,
       onStartTraining = null,
       runId = '',
       decisionPath = null,
       decisionTitle = "2차 AI 피드백";
  const ChatGPTAnalysisPanel.decision({
    super.key,
    required this.repository,
    required this.decisionPath,
    required this.decisionTitle,
    this.autoGenerate = true,
    this.onStatusChanged,
    this.journalReview = false,
    this.journalConsentMessage,
  }) : onStartTraining = null,
       currentPrice = null,
       runId = '',
       checkId = null;
  final WorkspaceRepository repository;
  final String runId;
  final String? checkId;
  final String? decisionPath, decisionTitle;
  final bool autoGenerate;
  final bool journalReview;
  final String? journalConsentMessage;
  final int? currentPrice;
  final VoidCallback? onStartTraining;
  final ValueChanged<String>? onStatusChanged;

  @override
  State<ChatGPTAnalysisPanel> createState() => _ChatGPTAnalysisPanelState();
}

class _ChatGPTAnalysisPanelState extends State<ChatGPTAnalysisPanel> {
  Map<String, dynamic> _review = {};
  String? _error;
  bool _busy = false;
  Timer? _timer;
  int _polls = 0;

  bool get _retrospective =>
      widget.checkId == null && widget.decisionPath == null;

  String get _path =>
      widget.decisionPath ??
      (widget.checkId == null
          ? '/v1/replay/runs/${widget.runId}/ai-review'
          : '/v1/orders/check/${widget.checkId}/ai-feedback');

  @override
  void initState() {
    super.initState();
    _load(create: widget.autoGenerate);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _applyReview(Map<String, dynamic> review) {
    setState(() => _review = review);
    final status = '${review['status']}';
    widget.onStatusChanged?.call(status);
    _timer?.cancel();
    if ((status == 'pending' || status == 'generating') && _polls < 140) {
      _timer = Timer(const Duration(seconds: 2), () {
        _polls++;
        _load();
      });
    }
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
      _applyReview(result);
    } catch (error) {
      if (!mounted) return;
      widget.onStatusChanged?.call('failed');
      if (create) {
        try {
          final status = await widget.repository.workspaceRequest('GET', _path);
          if (!mounted) return;
          _applyReview(status);
          if ([
            'available',
            'pending',
            'generating',
          ].contains(status['status'])) {
            return;
          }
        } catch (_) {
          /* Preserve the original request failure. */
        }
      }
      if (mounted) {
        setState(
          () => _error = error is ApiException
              ? error.message
              : 'AI 연결을 확인한 뒤 다시 분석해 주세요.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _generate() async {
    if (!_retrospective && !widget.journalReview) {
      _polls = 0;
      await _load(create: true);
      return;
    }
    final scope =
        widget.journalConsentMessage ??
        (widget.journalReview
            ? '선택한 기록의 주문, 체결, 계획, 경고, 거래 이유와 복기 메모를 '
                  'OpenAI에 전달해 복기를 생성합니다. 결과는 일지에 저장됩니다.'
            : '이 실험의 행동 집계를 OpenAI에 전달합니다. '
                  '종목명·날짜·계좌정보·입력한 이유·메모는 보내지 않습니다. '
                  '본인 ChatGPT 구독 한도를 사용하며 별도 유료 API로 전환하지 않습니다. '
                  '생성한 해설은 복기 기록에 저장됩니다. 계속할까요?');
    final consent = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ChatGPT로 AI 복기 생성'),
        content: Text(scope),
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
    final training = _review['training'] as Map?;
    final facts = {
      for (final f in _review['facts'] as List? ?? []) f['fact_id']: f['text'],
    };
    return Card(
      key: const ValueKey('ai-review-card'),
      margin: widget.checkId != null ? EdgeInsets.zero : null,
      child: Padding(
        padding: widget.checkId != null
            ? const EdgeInsets.symmetric(vertical: 8)
            : const EdgeInsets.all(15),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              widget.decisionTitle ??
                  (_retrospective ? 'ChatGPT AI 복기' : 'ChatGPT'),
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            if (_retrospective)
              const Text(
                'ON/OFF 두 실험 종료 후 제공하는 선택 기능입니다. 서버 집계와 AI 해설을 구분해 확인하세요.',
              ),
            const SizedBox(height: 8),
            if (_error != null) Text(_error!),
            if (_review['message'] is String)
              Text(_review['message'] as String),
            if ([
              'not_connected',
              'reauth_required',
              'model_required',
              'consent_required',
              'identity_invalid',
            ].contains(_review['reason']))
              ChatGPTConnectionGuide(repository: widget.repository),
            if (_busy) const Text('연결 상태 확인 중…'),
            if (status == 'pending' || status == 'generating')
              const Text('AI 피드백 생성 중입니다. 결과를 받으면 여기에 표시합니다.'),
            if (widget.checkId != null &&
                (status == 'available' || _review['quote_context'] != null))
              TradeAiEvidence(
                review: _review,
                currentPrice: widget.currentPrice,
              ),
            if (widget.checkId == null &&
                status == 'available' &&
                result?['kind'] == 'quant_web') ...[
              _ReportMarkdown(_withoutInlineSources('${result!['body']}')),
              _AnalysisSources(_review),
              if (_review['search']?['completed_calls'] case final int count
                  when count > 0)
                Text(
                  '웹 검색 $count회 완료',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              if (_review['analysis_as_of'] case final String stamp)
                Text(
                  '분석 요청 시점 $stamp',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
            ] else if (widget.checkId == null &&
                status == 'available' &&
                {
                  'decision_feedback',
                  'market_snapshot',
                }.contains(result?['kind'])) ...[
              if (result?['kind'] == 'market_snapshot')
                const Text('실제 체결·5분봉 요약 기반 · 웹 검색 미사용'),
              _ReportMarkdown('${result!['body']}'),
            ] else if (widget.journalReview &&
                status == 'available' &&
                result?['kind'] == 'journal_review') ...[
              for (final section in result!['sections'] as List) ...[
                const SizedBox(height: 18),
                Text(
                  '${section['title']}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 6),
                SelectableText('${section['text']}'),
                Text(
                  "참고 기록 · ${(section['fact_ids'] as List).map((id) => facts[id]).whereType<String>().join(' · ')}",
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ] else if (_retrospective &&
                status == 'available' &&
                result != null) ...[
              for (final item in result['observations'] as List) ...[
                const SizedBox(height: 12),
                Text(
                  '${widget.checkId == null ? '서버 집계' : '주문 시점 근거'} · ${facts[item['fact_id']] ?? ''}',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                Text('AI 해설 · ${item['interpretation']}'),
                Text(
                  '${widget.checkId == null ? '돌아볼 질문' : '주문 전 확인 질문'} · ${item['reflection_question']}',
                ),
              ],
              const SizedBox(height: 12),
              Text('해석의 한계 · ${result['limitation']}'),
              const Text('생성형 AI의 해설은 사실 확인이 필요하며 감정 진단·주가 예측·주문 지시가 아닙니다.'),
              if (training != null && widget.onStartTraining != null) ...[
                const SizedBox(height: 16),
                Text(
                  '다음 훈련 · ${training['title']}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text('${training['goal']}'),
                if (training['question'] case final String question)
                  Text('AI 확인 질문 · $question'),
                const Text('같은 사례를 Pilot ON으로 다시 연습합니다.'),
                FilledButton(
                  key: const ValueKey('replay-start-training'),
                  onPressed: _busy ? null : widget.onStartTraining,
                  child: const Text('이 상황 다시 연습하기'),
                ),
              ],
              ExpansionTile(
                title: const Text('AI 피드백 생성 기록'),
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
                    child: Text(
                      status != 'ready'
                          ? '다시 분석'
                          : widget.journalReview
                          ? 'AI 복기 생성'
                          : 'AI 피드백 받기',
                    ),
                  ),
                TextButton(
                  key: const ValueKey('ai-review-refresh'),
                  onPressed: _busy
                      ? null
                      : () {
                          _polls = 0;
                          _load();
                        },
                  child: Text(widget.checkId == null ? '새로고침' : '분석 상태 확인'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Reuses the original report, prices and source links in the confirmation and journal.
class TradeAiEvidence extends StatelessWidget {
  const TradeAiEvidence({super.key, required this.review, this.currentPrice});

  final Map review;
  final int? currentPrice;

  @override
  Widget build(BuildContext context) {
    final quote = review['quote_context'] as Map?;
    final price = int.tryParse('${quote?['current_price']}');
    final analysisTime = koreanMarketTime(
      review['analysis_as_of'],
      seconds: true,
    );
    final quoteTime = koreanMarketTime(quote?['quote_as_of'], seconds: true);
    final result = review['result'] as Map?;
    final body = result?['body'] as String?;
    final lines =
        body
            ?.split('\n')
            .map((line) => line.replaceFirst(RegExp(r'^[#>*\s]+'), '').trim())
            .where((line) => line.isNotEmpty)
            .toList() ??
        const <String>[];
    final summary =
        result?['summary'] as String? ??
        result?['judgment'] as String? ??
        lines.where((line) => line.contains('최종 판단')).firstOrNull ??
        (lines.firstOrNull == '요약' && lines.length > 1
            ? lines[1]
            : lines.firstOrNull);
    final difference = currentPrice == null || price == null
        ? null
        : currentPrice! - price;
    final style = Theme.of(context).textTheme.bodySmall;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (analysisTime != null)
          Text('분석 기준 · $analysisTime (KST)', style: style),
        if (quote != null)
          Text(
            price == null
                ? 'AI에 제공한 현재가 없음'
                : 'AI가 본 시세 · ${won(price)}원${quoteTime == null ? '' : ' ($quoteTime KST)'}',
            style: style,
          ),
        if (difference != null)
          Text(
            '현재 표시가 − AI 기준가 · ${difference > 0 ? '+' : ''}${won(difference)}원',
            style: style,
          ),
        if (summary != null && summary.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              summary,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ),
        if (body != null && body.isNotEmpty)
          ExpansionTile(
            dense: true,
            tilePadding: EdgeInsets.zero,
            title: const Text('AI 상세 분석 보기'),
            expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _ReportMarkdown(_withoutInlineSources(body)),
              _AnalysisSources(review),
            ],
          ),
      ],
    );
  }
}

class _AnalysisSources extends StatelessWidget {
  const _AnalysisSources(this.review);

  final Map review;

  Future<void> _openSource(BuildContext context, Uri uri) async {
    try {
      if (await launchUrl(uri, mode: LaunchMode.externalApplication)) return;
    } catch (_) {
      // Show the same message if the device has no browser available.
    }
    if (context.mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('출처 링크를 열지 못했습니다.')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final entries = (review['search'] as Map?)?['sources'] as List? ?? [];
    final sources = <Uri, String>{};
    for (final entry in entries.whereType<Map>()) {
      final uri = Uri.tryParse('${entry['url']}');
      if (uri == null ||
          uri.scheme != 'https' ||
          uri.host.isEmpty ||
          uri.userInfo.isNotEmpty) {
        continue;
      }
      final title = entry['title']?.toString().trim() ?? '';
      sources.putIfAbsent(uri, () => title.isEmpty ? uri.host : title);
    }
    if (sources.isEmpty) return const SizedBox.shrink();
    return ExpansionTile(
      title: Text('출처 더보기', style: Theme.of(context).textTheme.labelSmall),
      dense: true,
      tilePadding: EdgeInsets.zero,
      expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final source in sources.entries)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            title: Text(source.value),
            subtitle: Text(source.key.host),
            trailing: const Icon(Icons.open_in_new, size: 14),
            onTap: () => _openSource(context, source.key),
          ),
      ],
    );
  }
}

// Older reports store provider citations as inline Markdown links.
String _withoutInlineSources(String body) {
  final link = RegExp(
    r'\[([^\]\n]*)\]\(<?https?://(?:[^\s()<>]|\([^\s()]*\))+>?(?:\s+"[^"\n]*")?\)',
  );
  final url = RegExp(r'<?https?://[^\s<>`|]+>?');
  final sourceLabel = RegExp(r'^(?:출처|자료 출처|참고 자료|참고 링크)(?:\s*\d+)?$');
  final sourceList = RegExp(
    r'^\s*(?:[-*+]\s+)?(?:\*\*)?(?:확인 자료 URL|출처(?: 목록)?|참고 링크)\s*[:：]',
  );
  return body
      .split('\n')
      .map((line) {
        if (!url.hasMatch(line)) return line;
        final withoutLinks = line.replaceAll(link, '').replaceAll(url, '');
        if (sourceList.hasMatch(line) ||
            RegExp(r'^[\s`*<>()[\]·,.;:-]*$').hasMatch(withoutLinks)) {
          return '';
        }
        return line
            .replaceAllMapped(link, (match) {
              final label = match[1]!.trim();
              return sourceLabel.hasMatch(label) ? '' : label;
            })
            .replaceAll(RegExp(r'`https?://[^`\n]+`'), '')
            .replaceAll(url, '')
            .trimRight();
      })
      .join('\n');
}

class _ReportMarkdown extends StatelessWidget {
  const _ReportMarkdown(this.body);
  final String body;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final prose = (theme.textTheme.bodyMedium ?? const TextStyle()).copyWith(
      fontSize: 15,
      height: 1.6,
    );
    final heading = prose.copyWith(fontWeight: FontWeight.w700, height: 1.35);
    return LayoutBuilder(
      builder: (context, constraints) => MarkdownBody(
        data: body,
        selectable: true,
        fitContent: false,
        imageBuilder: (uri, title, alt) => const SizedBox.shrink(),
        styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
          p: prose,
          h1: heading.copyWith(fontSize: 23),
          h2: heading.copyWith(fontSize: 19),
          h2Padding: const EdgeInsets.only(top: 6),
          h3: heading.copyWith(fontSize: 17),
          blockSpacing: 12,
          listIndent: 19,
          blockquote: prose,
          blockquotePadding: const EdgeInsets.symmetric(
            horizontal: 14,
            vertical: 10,
          ),
          blockquoteDecoration: BoxDecoration(
            color: colors.primary.withValues(alpha: 0.08),
            border: Border(left: BorderSide(color: colors.primary, width: 3)),
          ),
          tableHead: heading.copyWith(fontSize: 13),
          tableHeadAlign: TextAlign.left,
          tableBody: prose.copyWith(fontSize: 13, height: 1.45),
          tableColumnWidth: FixedColumnWidth(
            (constraints.maxWidth / 3).clamp(108, 190).toDouble(),
          ),
          tableCellsPadding: const EdgeInsets.all(8),
          tableHeadCellsDecoration: BoxDecoration(
            color: colors.surfaceContainerHighest,
          ),
          tableBorder: TableBorder.all(color: colors.outlineVariant),
        ),
      ),
    );
  }
}

class ChatGPTConnectionGuide extends StatefulWidget {
  const ChatGPTConnectionGuide({super.key, required this.repository});
  final WorkspaceRepository repository;
  @override
  State<ChatGPTConnectionGuide> createState() => _ChatGPTConnectionGuideState();
}

class _ChatGPTConnectionGuideState extends State<ChatGPTConnectionGuide> {
  Map<String, dynamic>? _connection;
  Future<void> _check() async {
    try {
      final result = await widget.repository.workspaceRequest(
        'GET',
        '/v1/ai/connection',
      );
      if (mounted) setState(() => _connection = result);
    } catch (_) {
      if (mounted) {
        setState(
          () => _connection = {'message': '연결 상태를 확인하지 못했습니다. 서버 연결을 확인하세요.'},
        );
      }
    }
  }

  @override
  void initState() {
    super.initState();
    _check();
  }

  @override
  Widget build(BuildContext context) => ExpansionTile(
    title: const Text('ChatGPT 연결 안내'),
    childrenPadding: const EdgeInsets.all(12),
    expandedCrossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text('${_connection?['message'] ?? '연결 상태 확인 중…'}'),
      if (_connection?['model'] != null)
        Text('선택 모델: ${_connection!['model']}'),
      if (_connection?['command'] is String) ...[
        const Text(
          '서버를 실행한 Mac의 프로젝트 폴더에서 연결 명령을 실행하세요. 앱 이메일·앱 비밀번호 확인 후 브라우저에서 본인 ChatGPT 계정으로 로그인하고 모델을 선택합니다. 비밀번호·토큰을 채팅에 보내지 마세요.',
        ),
        const SelectableText('./tool/connect_chatgpt.sh'),
        TextButton.icon(
          icon: const Icon(Icons.copy),
          label: const Text('연결 명령 복사'),
          onPressed: () async {
            await Clipboard.setData(
              const ClipboardData(text: './tool/connect_chatgpt.sh'),
            );
          },
        ),
        const Text(
          '본인 ChatGPT 구독 사용 권한과 이용 한도가 적용됩니다. 앱의 TradePilot 로그인과 별도 연결이며 ChatGPT 대화 내역을 가져오지 않습니다.',
        ),
      ],
      TextButton(onPressed: _check, child: const Text('연결 상태 확인')),
    ],
  );
}
