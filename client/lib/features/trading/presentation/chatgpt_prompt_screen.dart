import 'package:flutter/material.dart';

import '../domain/workspace_repository.dart';

enum ChatGPTPromptTarget {
  chart('차트 분석', '차트 데이터만 사용할 때의 기본 프롬프트'),
  order('주문 전 분석', '차트 분석 결과가 없을 때의 기본 프롬프트');

  const ChatGPTPromptTarget(this.label, this.alternateLabel);

  final String label;
  final String alternateLabel;
}

class ChatGPTPromptScreen extends StatefulWidget {
  const ChatGPTPromptScreen({
    super.key,
    required this.repository,
    required this.target,
  });

  final WorkspaceRepository repository;
  final ChatGPTPromptTarget target;

  @override
  State<ChatGPTPromptScreen> createState() => _ChatGPTPromptScreenState();
}

class _ChatGPTPromptScreenState extends State<ChatGPTPromptScreen> {
  final _editor = TextEditingController();
  late Future<Map<String, dynamic>> _request;
  bool _saving = false;
  String? _saveMessage;

  String get _path => '/v1/ai/prompts/${widget.target.name}';

  @override
  void initState() {
    super.initState();
    _request = _load();
  }

  @override
  void dispose() {
    _editor.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _load() async {
    final data = await widget.repository.workspaceRequest('GET', _path);
    if (mounted) _editor.text = data['text'] as String;
    return data;
  }

  Future<void> _save({bool reset = false}) async {
    final text = _editor.text.trim();
    if (_saving || (!reset && text.isEmpty)) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _saving = true;
      _saveMessage = null;
    });
    try {
      final data = await widget.repository.workspaceRequest(
        'PUT',
        _path,
        body: {'text': reset ? null : text},
      );
      if (!mounted) return;
      _editor.text = data['text'] as String;
      setState(() {
        _request = Future.value(data);
        _saveMessage = reset ? '기본 프롬프트로 복원했어요.' : '프롬프트를 저장했어요.';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _saveMessage = '프롬프트를 저장하지 못했어요. 다시 시도해 주세요.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text('${widget.target.label} 프롬프트')),
    body: SafeArea(
      top: false,
      child: FutureBuilder<Map<String, dynamic>>(
        future: _request,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: TextButton(
                onPressed: () => setState(() => _request = _load()),
                child: const Text('불러오기 실패 · 다시 시도'),
              ),
            );
          }
          final data = snapshot.data;
          if (data == null) {
            return const Center(child: CircularProgressIndicator());
          }
          final customized = data['customized'] == true;
          final savedText = data['text'] as String;
          final alternate = data['alternate_default'] as String;
          return Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  customized ? '현재 사용 중 · 사용자 설정' : '현재 사용 중 · 기본값',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 4),
                const Text('저장한 내용은 이 계정의 다음 분석 요청부터 적용됩니다.'),
                const SizedBox(height: 12),
                Expanded(
                  child: TextField(
                    controller: _editor,
                    expands: true,
                    minLines: null,
                    maxLines: null,
                    maxLength: 12000,
                    readOnly: _saving,
                    textAlignVertical: TextAlignVertical.top,
                    decoration: const InputDecoration(hintText: '분석에 사용할 프롬프트'),
                  ),
                ),
                if (!customized)
                  TextButton(
                    onPressed: _saving
                        ? null
                        : () => showDialog<void>(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: Text(widget.target.alternateLabel),
                              content: SingleChildScrollView(
                                child: SelectableText(alternate),
                              ),
                              actions: [
                                TextButton(
                                  onPressed: () => Navigator.pop(context),
                                  child: const Text('닫기'),
                                ),
                              ],
                            ),
                          ),
                    child: Text(widget.target.alternateLabel),
                  ),
                if (_saveMessage case final message?)
                  Semantics(liveRegion: true, child: Text(message)),
                ValueListenableBuilder(
                  valueListenable: _editor,
                  builder: (context, value, _) {
                    final text = value.text.trim();
                    return Wrap(
                      alignment: WrapAlignment.end,
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        OutlinedButton(
                          onPressed: customized && !_saving
                              ? () => _save(reset: true)
                              : null,
                          child: const Text('기본값 복원'),
                        ),
                        FilledButton(
                          onPressed:
                              !_saving && text.isNotEmpty && text != savedText
                              ? _save
                              : null,
                          child: Text(_saving ? '저장 중…' : '저장'),
                        ),
                      ],
                    );
                  },
                ),
              ],
            ),
          );
        },
      ),
    ),
  );
}
