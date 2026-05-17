using GreenWaveAPI.Application.DTOs;
using MediatR;
using System.Text.Json.Serialization;

namespace GreenWaveAPI.Application.Features.Traffic.Commands;

public class CreateTrafficCommandRequest : IRequest<Unit>
{

    [JsonPropertyName("received_time")]
    public DateTime ReceivedTime { get; set; }

    [JsonPropertyName("junction_id")]
    public int JunctionId { get; set; }

    [JsonPropertyName("roads")]
    public List<RoadDto> Roads { get; set; } = new();
}