from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from forge.main.recommendations.engine import build_context, evaluate


class RecommendationsList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        scope = request.query_params.get('scope', 'all')
        ctx = build_context()
        recs = evaluate(scope, ctx)
        return Response({'count': len(recs), 'results': [r.to_dict() for r in recs]})
