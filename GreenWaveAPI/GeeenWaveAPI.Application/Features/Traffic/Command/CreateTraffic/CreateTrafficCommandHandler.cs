using GreenWaveAPI.Application.DTOs;
using GreenWaveAPI.Application.Interfaces;
using MediatR;
using System.Net.Http;
using System.Net.Http.Json;

namespace GreenWaveAPI.Application.Features.Traffic.Commands;

public class CreateTrafficCommandHandler
    : IRequestHandler<CreateTrafficCommandRequest, Unit>
{
    private readonly IFileService _fileService;
    private readonly ISumoService _sumoService;

    public CreateTrafficCommandHandler(
        IFileService fileService,
        ISumoService sumoService)
    {
        _fileService = fileService;
        _sumoService = sumoService;
    }

    public async Task<Unit> Handle(
        CreateTrafficCommandRequest request,
        CancellationToken cancellationToken)
    {
        var receivedTime = DateTime.UtcNow;

        var sumoDto = new SumoTrafficDto
        {
            ReceivedTime = receivedTime,
            SavedTime = null,
            JunctionId = request.JunctionId,
            Roads = request.Roads.Select(r => new SumoRoadDto
            {
                RoadId = r.RoadId,
                CongestionScore = r.CongestionScore,
                Ambulance = r.Ambulance
            }).ToList()
        };

        await _fileService.SaveJsonAsync(sumoDto);

        // Bridge camera scores into backend PostgreSQL aggregation endpoint.
        try
        {
            var backendBaseUrl = Environment.GetEnvironmentVariable("GREENWAVE_BACKEND_BASE_URL") ?? "http://127.0.0.1:5000";
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };

            var payload = new
            {
                junction_id = request.JunctionId,
                received_time = receivedTime,
                scores = request.Roads.Select(r => r.CongestionScore).ToArray()
            };

            var endpoint = $"{backendBaseUrl.TrimEnd('/')}/camera/congestion";
            using var response = await client.PostAsJsonAsync(endpoint, payload, cancellationToken);
        }
        catch
        {
            // Do not block SUMO flow if DB bridge fails.
        }

        try
        {
            await _sumoService.SendToSumoAsync(sumoDto);

            sumoDto.SavedTime = DateTime.UtcNow;

            await _fileService.SaveJsonAsync(sumoDto);
        }
        catch (Exception)
        {
            throw;
        }

        return Unit.Value;
    }
}
