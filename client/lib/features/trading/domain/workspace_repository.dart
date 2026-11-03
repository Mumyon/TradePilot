/// Account/market management supported by the persistent server repository.
abstract interface class WorkspaceRepository {
  Future<Map<String, dynamic>> workspaceRequest(
    String method,
    String path, {
    Map<String, dynamic>? body,
  });
}
