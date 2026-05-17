using MediatR;
using GreenWaveAPI.Application.DTOs;

namespace GreenWaveAPI.Application.Features.Traffic.Queries
{
    public class GetLatestTrafficQuery : IRequest<SumoTrafficDto>
    {
        public int JunctionId { get; set; } 
    }
}