import 'dart:convert';
import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import '../domain/workspace_repository.dart';

class DatasetScreen extends StatefulWidget {
  const DatasetScreen({super.key, required this.repository, this.pickFile});
  final WorkspaceRepository repository;
  final Future<XFile?> Function()? pickFile;
  @override
  State<DatasetScreen> createState() => _DatasetScreenState();
}

class _DatasetScreenState extends State<DatasetScreen> {
  final _name = TextEditingController(),
      _symbol = TextEditingController(text: '005930'),
      _provider = TextEditingController();
  String _kind = 'synthetic';
  String? _csv, _file, _error;
  Map<String, dynamic>? _validation;
  List<dynamic> _items = [];
  bool _busy = false;
  @override
  void initState() {
    super.initState();
    _perform(_load);
  }

  @override
  void dispose() {
    _name.dispose();
    _symbol.dispose();
    _provider.dispose();
    super.dispose();
  }

  Future<void> _perform(Future<void> Function() fn) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await fn();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _load() async {
    final result = await widget.repository.workspaceRequest(
      'GET',
      '/v1/datasets',
    );
    if (mounted) setState(() => _items = result['items'] as List);
  }

  Map<String, dynamic> _body() {
    if (_name.text.trim().isEmpty ||
        _provider.text.trim().isEmpty ||
        _symbol.text.trim().isEmpty) {
      throw Exception('데이터 이름·종목 코드·출처를 모두 입력하세요.');
    }
    return {
      'name': _name.text.trim(),
      'symbol': _symbol.text.trim(),
      'provider': _provider.text.trim(),
      'data_kind': _kind,
      'csv_text': _csv,
    };
  }

  void _changed([String? value]) => setState(() => _validation = null);
  Future<void> _pick() async {
    final file =
        await (widget.pickFile?.call() ??
            openFile(
              acceptedTypeGroups: const [
                XTypeGroup(
                  label: 'CSV',
                  extensions: ['csv'],
                  uniformTypeIdentifiers: [
                    'public.comma-separated-values-text',
                  ],
                ),
              ],
            ));
    if (file == null) return;
    if (await file.length() > 3000000) {
      throw Exception('CSV는 3MB 이하만 선택할 수 있습니다.');
    }
    final csv = utf8.decode(await file.readAsBytes());
    if (!mounted) return;
    setState(() {
      _csv = csv;
      _file = file.name;
      _name.text = file.name;
      _validation = null;
    });
  }

  Widget _summary(Map<String, dynamic> row) => Text(
    '${row['bar_count']}개 봉 · 최대 연속 ${row['longest_contiguous']}개 · 단절 ${row['gap_count']}곳\n${row['first_bar']} ~ ${row['last_bar']}',
  );
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('CSV 연구 데이터')),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('본인 계정의 백테스트 전용 데이터입니다. 공용 시세·자동매매·AI 모델에 자동 적용하지 않습니다.'),
          const SizedBox(height: 12),
          const SelectableText(
            'UTF-8 · 최대 3MB/20,000행\nopened_at,open_won,high_won,low_won,close_won,volume\n시간대 포함 5분봉 시작 시각, 평일 한국시간 09:00~15:25, 시간 오름차순. 가격은 양의 정수, 거래량은 0 이상입니다.',
          ),
          const SizedBox(height: 16),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
          OutlinedButton(
            onPressed: _busy ? null : () => _perform(_pick),
            child: const Text('CSV 파일 선택'),
          ),
          if (_file != null) Text(_file!),
          TextField(
            enabled: !_busy,
            controller: _name,
            onChanged: _changed,
            maxLength: 100,
            decoration: const InputDecoration(labelText: '데이터 이름'),
          ),
          TextField(
            enabled: !_busy,
            controller: _symbol,
            onChanged: _changed,
            decoration: const InputDecoration(labelText: '종목 코드'),
          ),
          TextField(
            enabled: !_busy,
            controller: _provider,
            onChanged: _changed,
            maxLength: 100,
            decoration: const InputDecoration(labelText: '데이터 출처 (제공처/생성 방법)'),
          ),
          DropdownButtonFormField<String>(
            initialValue: _kind,
            decoration: const InputDecoration(labelText: '데이터 종류'),
            items: const [
              DropdownMenuItem(value: 'synthetic', child: Text('합성·테스트 데이터')),
              DropdownMenuItem(
                value: 'historical',
                child: Text('과거 주가 (사용자 선언)'),
              ),
            ],
            onChanged: _busy
                ? null
                : (v) {
                    setState(() {
                      _kind = v!;
                      _validation = null;
                    });
                  },
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy || _csv == null
                ? null
                : () => _perform(() async {
                    final result = await widget.repository.workspaceRequest(
                      'POST',
                      '/v1/datasets/validate',
                      body: _body(),
                    );
                    if (mounted) setState(() => _validation = result);
                  }),
            child: const Text('등록 전 검증'),
          ),
          if (_validation case final value?) ...[
            _summary(value),
            Text('${value['warning']}'),
            FilledButton(
              onPressed: _busy
                  ? null
                  : () => _perform(() async {
                      await widget.repository.workspaceRequest(
                        'POST',
                        '/v1/datasets',
                        body: _body(),
                      );
                      await _load();
                      if (mounted) {
                        setState(() {
                          _validation = null;
                          _csv = null;
                          _file = null;
                        });
                      }
                    }),
              child: const Text('검증한 데이터 저장'),
            ),
          ],
          const Divider(height: 32),
          const Text('내 데이터 목록'),
          if (_items.isEmpty) const Text('등록된 데이터가 없습니다.'),
          for (final raw in _items)
            Builder(
              builder: (context) {
                final row = Map<String, dynamic>.from(raw as Map);
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${row['name']} · ${row['symbol']}',
                        style: const TextStyle(fontWeight: FontWeight.bold),
                      ),
                      Text(
                        '${row['data_kind'] == 'synthetic' ? '합성' : '과거 데이터 (미검증)'} · ${row['provider']}',
                      ),
                      _summary(row),
                      Wrap(
                        spacing: 12,
                        children: [
                          FilledButton(
                            onPressed: _busy
                                ? null
                                : () => Navigator.pop(context, row),
                            child: const Text('백테스트에서 사용'),
                          ),
                          TextButton(
                            onPressed: _busy
                                ? null
                                : () async {
                                    final confirmed = await showDialog<bool>(
                                      context: context,
                                      builder: (context) => AlertDialog(
                                        title: const Text('데이터 삭제'),
                                        content: Text(
                                          '${row['name']} 데이터를 삭제합니다. 이미 저장한 백테스트 결과는 유지됩니다.',
                                        ),
                                        actions: [
                                          TextButton(
                                            onPressed: () =>
                                                Navigator.pop(context, false),
                                            child: const Text('취소'),
                                          ),
                                          FilledButton(
                                            onPressed: () =>
                                                Navigator.pop(context, true),
                                            child: const Text('삭제'),
                                          ),
                                        ],
                                      ),
                                    );
                                    if (confirmed == true && mounted) {
                                      await _perform(() async {
                                        await widget.repository
                                            .workspaceRequest(
                                              'DELETE',
                                              '/v1/datasets/${row['id']}',
                                            );
                                        await _load();
                                      });
                                    }
                                  },
                            child: const Text('데이터 삭제'),
                          ),
                        ],
                      ),
                    ],
                  ),
                );
              },
            ),
        ],
      ),
    ),
  );
}
